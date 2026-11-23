import copy
import random
from collections import deque

import torch
from torch import nn
from torch.nn import functional as F

from .engine import LinearEngine, STAGES, TOOLS, softmax


class AttentionBlock(nn.Module):
    """Sheet attention: normalize(softmax(QK / (sqrt(d_k)^surface))^volume)V."""

    def __init__(self, width=32, heads=4):
        super().__init__()
        self.width, self.heads = width, heads
        self.qkv = nn.Linear(width, width * 3)
        self.project = nn.Linear(width, width)
        self.norm1, self.norm2 = nn.LayerNorm(width), nn.LayerNorm(width)
        self.ff = nn.Sequential(nn.Linear(width, width * 2), nn.ReLU(), nn.Linear(width * 2, width))

    def forward(self, x, surface, volume):
        batch, count, width = x.shape
        qkv = self.qkv(x).reshape(batch, count, 3, self.heads, width // self.heads)
        q, k, v = qkv.permute(2, 0, 3, 1, 4).unbind(0)
        logits = (q @ k.transpose(-2, -1)) / ((width // self.heads) ** (surface / 2))
        # softmax(volume*logits) is algebraically the normalized power of softmax(logits).
        attention = torch.softmax(logits * volume, dim=-1)
        output = (attention @ v).transpose(1, 2).reshape(batch, count, width)
        x = self.norm1(x + self.project(output))
        return self.norm2(x + self.ff(x))


class INNTransformer(nn.Module):
    def __init__(self, baseline, validity, width=32, layers=2):
        super().__init__()
        self.features = nn.Linear(5, width)
        self.tool = nn.Embedding(8, width)
        self.stage = nn.Embedding(8, width)
        self.plot = nn.Embedding(65, width)
        self.blocks = nn.ModuleList([AttentionBlock(width) for _ in range(layers)])
        self.q_head, self.gate_head = nn.Linear(width, 1), nn.Linear(width, 1)
        for head in (self.q_head, self.gate_head):
            nn.init.zeros_(head.weight)
            nn.init.zeros_(head.bias)
        self.register_buffer('base_q', torch.tensor([[w['b'], *w['x']] for w in baseline], dtype=torch.float32))
        gates = torch.zeros(8, 8)
        gates[:6, :6] = torch.tensor(validity, dtype=torch.float32)
        self.register_buffer('base_validity', gates)

    def forward(self, features, tools, stages, plots, surface, volume):
        x = self.features(features) + self.tool(tools) + self.stage(stages) + self.plot(plots)
        for block in self.blocks:
            x = block(x, surface, volume)
        base = self.base_q[tools]
        q = base[..., 0] + (base[..., 1:] * features).sum(-1) + self.q_head(x).squeeze(-1)
        gate_logits = self.base_validity[stages, tools] + self.gate_head(x).squeeze(-1)
        return q, gate_logits


class TransformerEngine(LinearEngine):
    kind = 'transformer'

    def __init__(self, config, state=None, device='cpu', train_every=32, seed=1):
        super().__init__(config, state)
        torch.manual_seed(seed)
        self.device = torch.device(device)
        self.model = INNTransformer(self.w, self.validity).to(self.device)
        self.target = copy.deepcopy(self.model).eval()
        self.optimizer = torch.optim.AdamW(self.model.parameters(), lr=.001, weight_decay=.01)
        self.replay = deque(maxlen=4096)
        self.train_every = train_every
        self.rng = random.Random(seed)
        self.transitions = 0
        self.optimizer_steps = 0
        self.current_volume = 3.

    def tensors(self, items):
        stages = [STAGES.index(a['stage']) if a['stage'] in STAGES else 6 if a['stage'] == 'GROWING' else 7 for a in items]
        return (torch.tensor([[a['x'] for a in items]], device=self.device, dtype=torch.float32),
                torch.tensor([[TOOLS.index(a['t']) for a in items]], device=self.device),
                torch.tensor([stages], device=self.device),
                torch.tensor([[a['a'] for a in items]], device=self.device))

    def predictions(self, items, model=None):
        return (model or self.model)(*self.tensors(items), self.config['surface'], self.current_volume)

    def score(self, items, epsilon):
        self.current_volume = self.volume(epsilon)
        with torch.no_grad():
            q, logits = self.predictions(items)
            raw, gates = q[0].cpu().tolist(), torch.sigmoid(logits[0]).cpu().tolist()
        divisor = self.config['dk'] ** (self.config['surface'] / 2)
        f1 = softmax([v / divisor for v in raw])
        f2 = softmax([v / divisor * self.current_volume for v in raw])
        for i, a in enumerate(items):
            gate = gates[i] if a['stage'] in STAGES and TOOLS.index(a['t']) < 4 else 1.
            a.update(raw=raw[i], f1=f1[i], f2=f2[i], gate=gate,
                     score=f2[i] if gate >= self.config['threshold'] else 0.)
        return items

    def outcome(self, action, legal):
        self.last_legal = bool(legal)

    def learn(self, action, reward, next_items, context=None):
        legal = context['legal'] if isinstance(context, dict) else getattr(self, 'last_legal', False)
        context = context['items'] if isinstance(context, dict) else context or [action]
        index = next((i for i, a in enumerate(context) if (a['t'], a['a'], a['b']) == (action['t'], action['a'], action['b'])), 0)
        self.replay.append(dict(context=copy.deepcopy(context), index=index, reward=reward,
                                next=copy.deepcopy(next_items), legal=legal))
        self.transitions += 1
        self.updates += 1
        if self.transitions % self.train_every or len(self.replay) < 8:
            return
        # Ragged candidate sets retain their full attention context per sample.
        samples = self.rng.sample(list(self.replay), min(8, len(self.replay)))
        self.optimizer.zero_grad(set_to_none=True)
        total = 0.
        for sample in samples:
            q, gate = self.predictions(sample['context'])
            i = sample['index']
            with torch.no_grad():
                future = self.predictions(sample['next'], self.target)[0].max() if sample['next'] else torch.tensor(0., device=self.device)
                target = sample['reward'] + self.config['gamma'] * future
            loss = F.smooth_l1_loss(q[0, i], target)
            a = sample['context'][i]
            if a['stage'] in STAGES and TOOLS.index(a['t']) < 4:
                label = torch.tensor(float(sample['legal']), device=self.device)
                loss = loss + F.binary_cross_entropy_with_logits(gate[0, i], label)
            total = total + loss / len(samples)
        if not torch.isfinite(total):
            raise RuntimeError('Non-finite Transformer loss')
        total.backward()
        nn.utils.clip_grad_norm_(self.model.parameters(), 1.)
        self.optimizer.step()
        self.loss = float(total.detach())
        self.optimizer_steps += 1
        if self.optimizer_steps % 20 == 0:
            self.target.load_state_dict(self.model.state_dict())

    def state(self):
        return dict(super().state(), neural_transitions=self.transitions,
                    optimizer_steps=self.optimizer_steps, train_every=self.train_every)

    def save(self, path):
        torch.save(dict(model=self.model.state_dict(), target=self.target.state_dict(),
                        optimizer=self.optimizer.state_dict(), replay=list(self.replay),
                        transitions=self.transitions, optimizer_steps=self.optimizer_steps,
                        rng=self.rng.getstate(), torch_rng=torch.get_rng_state()), path)

    def load(self, path):
        checkpoint = torch.load(path, map_location=self.device, weights_only=False)
        self.model.load_state_dict(checkpoint['model'])
        self.target.load_state_dict(checkpoint['target'])
        self.optimizer.load_state_dict(checkpoint['optimizer'])
        self.replay.extend(checkpoint['replay'])
        self.transitions = checkpoint['transitions']
        self.optimizer_steps = checkpoint['optimizer_steps']
        self.rng.setstate(checkpoint['rng'])
        torch.set_rng_state(checkpoint['torch_rng'].cpu())
