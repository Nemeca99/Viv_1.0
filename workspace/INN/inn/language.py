"""Own byte language model and farm heads sharing the existing INN attention.

No pretrained language weights, lookup-table responses, or template fallback.
Templates are supervised targets only; inference always decodes neural logits.
"""
import copy
import torch
from torch import nn
from torch.nn import functional as F
from .transformer import INNTransformer, TransformerEngine
from .uml_neural_gate import uml_clip_and_stabilize_gradients, uml_sanitize_loss


def counterfactual_rank_loss(q_values, score_advantages, legal):
    if len(score_advantages) != q_values.numel() or len(legal) != q_values.numel():
        raise ValueError('Counterfactual targets and legality labels must align with candidate actions')
    comparisons = []
    for left in range(q_values.numel()):
        if not legal[left]:
            continue
        for right in range(left + 1, q_values.numel()):
            if not legal[right] or score_advantages[left] == score_advantages[right]:
                continue
            direction = 1.0 if score_advantages[left] > score_advantages[right] else -1.0
            comparisons.append(F.softplus(-direction * (q_values[left] - q_values[right])))
    return torch.stack(comparisons).mean() if comparisons else q_values.sum() * 0.0


class ByteTokenizer:
    PAD, BOS, EOS = 256, 257, 258
    size = 259

    @staticmethod
    def encode(text):
        return list(text.encode('utf-8'))

    @staticmethod
    def decode(tokens):
        return bytes(t for t in tokens if 0 <= t < 256).decode('utf-8', errors='replace')


class GroundedINN(INNTransformer):
    def __init__(self, baseline, validity, width=64, layers=2, vocab_size=259, context_length=192):
        super().__init__(baseline, validity, width, layers)
        self.token = nn.Embedding(vocab_size, width)
        self.position = nn.Embedding(context_length, width)
        self.lm_head = nn.Linear(width, vocab_size)

    def language(self, tokens, surface=2., volume=3.):
        if tokens.shape[1] > self.position.num_embeddings:
            raise ValueError('Language input exceeds configured token context')
        x = self.token(tokens) + self.position(torch.arange(tokens.shape[1], device=tokens.device))
        for block in self.blocks:
            x = block(x, surface, volume, causal=True)
        return self.lm_head(x)


class LanguageEngine(TransformerEngine):
    model_type = GroundedINN

    def __init__(self, *args, tokenizer=None, context_length=192, **kwargs):
        self.tokenizer = tokenizer or ByteTokenizer
        self.context_length = context_length
        self.model_type = lambda baseline, validity: GroundedINN(
            baseline, validity, vocab_size=self.tokenizer.size, context_length=context_length)
        super().__init__(*args, **kwargs)

    def checkpoint_metadata(self):
        return {'language_contract': {'tokenizer': self.tokenizer.manifest() if hasattr(self.tokenizer, 'manifest') else {'schema': 'legacy_utf8_bytes_v1'},
                                     'context_length': self.context_length}}

    def validate_checkpoint(self, checkpoint):
        saved = checkpoint.get('language_contract')
        expected = self.checkpoint_metadata()['language_contract']
        if saved != expected and not (saved is None and self.tokenizer is ByteTokenizer and self.context_length == 192):
            raise ValueError('Checkpoint tokenizer/context contract mismatch')

    def migrate_byte_parent(self, path):
        """Copy compatible parent weights; start a fresh optimizer for new rows."""
        if not hasattr(self.tokenizer, 'characters'):
            raise ValueError('Migration requires a custom character tokenizer')
        parent = torch.load(path, map_location=self.device, weights_only=False)
        contract = parent.get('language_contract')
        if contract and contract['tokenizer']['schema'] != 'legacy_utf8_bytes_v1':
            raise ValueError('Migration source must be a byte checkpoint')
        old = parent['model']
        new = self.model.state_dict()
        remapped = {'token.weight', 'lm_head.weight', 'lm_head.bias', 'position.weight'}
        for name in new:
            if name not in remapped:
                if new[name].shape != old[name].shape:
                    raise ValueError(f'Parent architecture mismatch: {name}')
                new[name].copy_(old[name])
        for row, char in enumerate(self.tokenizer.characters):
            byte_rows = list(char.encode('utf-8'))
            for name in ('token.weight', 'lm_head.weight', 'lm_head.bias'):
                new[name][row].copy_(old[name][byte_rows].mean(dim=0))
        for special in ('PAD', 'BOS', 'EOS'):
            for name in ('token.weight', 'lm_head.weight', 'lm_head.bias'):
                new[name][getattr(self.tokenizer, special)].copy_(old[name][getattr(ByteTokenizer, special)])
        count = min(len(new['position.weight']), len(old['position.weight']))
        new['position.weight'][:count].copy_(old['position.weight'][:count])
        self.model.load_state_dict(new)
        self.freeze_target()

    def migrate_character_parent(self, path):
        """Explicit row migration when a new corpus expands the active alphabet."""
        from .tokenizer import INNCharacterTokenizer
        checkpoint = torch.load(path, map_location=self.device, weights_only=False)
        old_tokenizer = INNCharacterTokenizer.from_manifest(checkpoint['language_contract']['tokenizer'])
        old, new = checkpoint['model'], self.model.state_dict()
        remapped = {'token.weight', 'lm_head.weight', 'lm_head.bias', 'position.weight'}
        for name in new:
            if name not in remapped:
                if new[name].shape != old[name].shape:
                    raise ValueError(f'Parent architecture mismatch: {name}')
                new[name].copy_(old[name])
        for row, char in enumerate(self.tokenizer.characters):
            if char in old_tokenizer.stoi:
                for name in ('token.weight', 'lm_head.weight', 'lm_head.bias'):
                    new[name][row].copy_(old[name][old_tokenizer.stoi[char]])
        for special in ('PAD', 'BOS', 'EOS'):
            for name in ('token.weight', 'lm_head.weight', 'lm_head.bias'):
                new[name][getattr(self.tokenizer, special)].copy_(old[name][getattr(old_tokenizer, special)])
        count = min(len(new['position.weight']), len(old['position.weight']))
        new['position.weight'][:count].copy_(old['position.weight'][:count])
        self.model.load_state_dict(new)
        self.freeze_target()

    def language_batch(self, examples):
        sequences, targets = [], []
        for example in examples:
            prefix = [self.tokenizer.BOS, *self.tokenizer.encode(example['prompt'])]
            suffix = [*self.tokenizer.encode(example['target']), self.tokenizer.EOS]
            sequence = prefix + suffix
            if len(sequence) > self.context_length:
                raise ValueError('Training example exceeds context; no silent truncation')
            sequences.append(sequence[:-1])
            targets.append([-100] * (len(prefix) - 1) + suffix)
        length = max(map(len, sequences))
        x = torch.full((len(sequences), length), self.tokenizer.PAD, dtype=torch.long, device=self.device)
        y = torch.full_like(x, -100)
        for i, (sequence, labels) in enumerate(zip(sequences, targets)):
            x[i, :len(sequence)] = torch.tensor(sequence, device=self.device)
            y[i, :len(labels)] = torch.tensor(labels, device=self.device)
        logits = self.model.language(x, self.config['surface'], self.current_volume)
        return F.cross_entropy(logits.flatten(0, 1), y.flatten())

    def resume_character_parent(self, path):
        """Resume AdamW moments and counters even when the alphabet expands."""
        from .tokenizer import INNCharacterTokenizer
        checkpoint = torch.load(path, map_location=self.device, weights_only=False)
        old_tokenizer = INNCharacterTokenizer.from_manifest(checkpoint['language_contract']['tokenizer'])
        if checkpoint['language_contract']['context_length'] != self.context_length:
            raise ValueError('Resume requires the same context length')
        if not set(old_tokenizer.characters) <= set(self.tokenizer.characters):
            raise ValueError('Resume cannot remove existing characters')
        if old_tokenizer.manifest() == self.tokenizer.manifest():
            self.load(path)
            return
        self.migrate_character_parent(path)
        mapping = [(old_tokenizer.stoi[c], self.tokenizer.stoi[c]) for c in old_tokenizer.characters]
        mapping += [(getattr(old_tokenizer, s), getattr(self.tokenizer, s)) for s in ('PAD', 'BOS', 'EOS')]
        row_names = {'token.weight', 'lm_head.weight', 'lm_head.bias'}
        # Parameter order is unchanged; only the three vocabulary tensor shapes change.
        state = copy.deepcopy(checkpoint['optimizer'])
        ids = [i for group in state['param_groups'] for i in group['params']]
        parameters = list(self.model.named_parameters())
        if len(ids) != len(parameters):
            raise ValueError('Optimizer parameter layout changed')
        for (name, parameter), ident in zip(parameters, ids):
            for key, value in list(state['state'].get(ident, {}).items()):
                if not torch.is_tensor(value) or value.ndim == 0:
                    continue
                if name in row_names:
                    migrated = torch.zeros_like(parameter)
                    for old_row, new_row in mapping:
                        migrated[new_row].copy_(value[old_row])
                    state['state'][ident][key] = migrated
                elif value.shape != parameter.shape:
                    raise ValueError(f'Optimizer tensor layout changed: {name}')
        self.optimizer.load_state_dict(state)
        self.optimizer_steps = checkpoint['optimizer_steps']
        self.transitions = checkpoint['transitions']
        self.replay.extend(checkpoint['replay'])
        self.rng.setstate(checkpoint['rng'])
        torch.set_rng_state(checkpoint['torch_rng'].cpu())

    @torch.no_grad()
    def speak(self, prompt, max_new=48):
        tokens = [self.tokenizer.BOS, *self.tokenizer.encode(prompt)]
        if len(tokens) + max_new > self.context_length:
            raise ValueError('Requested generation exceeds context')
        generated = []
        for _ in range(max_new):
            x = torch.tensor([tokens], device=self.device)
            logits = self.model.language(x, self.config['surface'], self.current_volume)[0, -1].clone()
            if self.tokenizer is not ByteTokenizer:
                logits[[self.tokenizer.PAD, self.tokenizer.BOS]] = float('-inf')
            token = int(logits.argmax())
            if token == self.tokenizer.EOS:
                break
            generated.append(token)
            tokens.append(token)
        return self.tokenizer.decode(generated)

    def train_joint(self, examples, action_samples):
        self.optimizer.zero_grad(set_to_none=True)
        language_loss = self.language_batch(examples)
        action_loss = torch.zeros((), device=self.device)
        for sample in action_samples:
            q, gate = self.predictions(sample['items'])
            labels = torch.tensor(sample['legal'], device=self.device, dtype=torch.float32)
            action_loss = action_loss + F.binary_cross_entropy_with_logits(gate[0], labels)
            score_advantages = sample.get('counterfactual_score_advantages')
            if score_advantages is not None:
                action_loss = action_loss + counterfactual_rank_loss(q[0], score_advantages, sample['legal'])
            if sample.get('parent_raw') is not None:
                target_q = torch.tensor([sample['parent_raw']], device=self.device, dtype=torch.float32)
                action_loss = action_loss + self.config.get('neuralRetentionWeight', .1) * F.smooth_l1_loss(q, target_q)
            if sample.get('best') is not None and sample.get('oracle_improved'):
                # Match independently measured multi-tick Rust outcomes, not Queen agreement.
                action_loss = action_loss + F.cross_entropy(q * .6, torch.tensor([sample['best']], device=self.device))
        if action_samples:
            action_loss = action_loss / len(action_samples)
        loss = language_loss + action_loss
        loss, sanitized = uml_sanitize_loss(loss)
        loss.backward()
        grad_telemetry = uml_clip_and_stabilize_gradients(
            self.model.parameters(), max_norm=1., loss_value=float(loss.detach())
        )
        self.uml_grad_telemetry = grad_telemetry
        self.optimizer.step()
        self.optimizer_steps += 1
        self.loss = float(loss.detach())
        return {
            'language_loss': float(language_loss.detach()) if torch.isfinite(language_loss) else 0.,
            'action_loss': float(action_loss.detach()) if torch.isfinite(action_loss) else 0.,
            'uml_grad_state': grad_telemetry['state_tag'],
            'uml_grad_norm': grad_telemetry['grad_norm'],
            'uml_loss_sanitized': sanitized,
        }

    def freeze_target(self):
        self.target = copy.deepcopy(self.model).eval()
