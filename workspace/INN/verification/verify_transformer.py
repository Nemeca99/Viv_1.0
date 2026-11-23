import copy
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import torch
from inn.cli import checkpoint, load_checkpoint
from inn.engine import DEFAULT_CONFIG, Simulation
from inn.farm import Farm
from inn.transformer import AttentionBlock, TransformerEngine
from verify import compare


def main():
    torch.set_num_threads(1)
    folder = ROOT / f'verification/artifacts/transformer-resume-{time.time_ns()}'
    config = copy.deepcopy(DEFAULT_CONFIG)
    engine = TransformerEngine(config, train_every=8)
    attention_before = engine.model.blocks[0].qkv.weight.detach().clone()
    with Farm() as farm:
        sim = Simulation(farm, engine)
        for _ in range(64):
            sim.step()
        checkpoint(sim, folder)
        for _ in range(64):
            sim.step()
        expected = sim.snapshot()
        expected_weights = copy.deepcopy(engine.model.state_dict())
        assert not torch.equal(attention_before, engine.model.blocks[0].qkv.weight)
    state = load_checkpoint(folder)
    restored = TransformerEngine(config, state, train_every=8)
    restored.load(folder / 'engine.pt')
    with Farm(state) as farm:
        sim = Simulation(farm, restored, state)
        for _ in range(64):
            sim.step()
        compare(expected, sim.snapshot())
        for key, tensor in expected_weights.items():
            assert torch.equal(tensor, restored.model.state_dict()[key]), key
    # Independently compute normalized cubed softmax using the block's learned projections.
    block = AttentionBlock()
    x = torch.randn(1, 4, 32)
    q, k, v = block.qkv(x).reshape(1,4,3,4,8).permute(2,0,3,1,4).unbind(0)
    probabilities = torch.softmax((q @ k.transpose(-2,-1))/8, dim=-1).pow(3)
    probabilities = probabilities / probabilities.sum(-1, keepdim=True)
    output = (probabilities @ v).transpose(1,2).reshape(1,4,32)
    y = block.norm1(x + block.project(output))
    expected_output = block.norm2(y + block.ff(y))
    torch.testing.assert_close(expected_output, block(x,2,3), atol=1e-6, rtol=1e-5)
    receipt = dict(status='PASS', attention_formula='normalized cubed softmax with square dimension divisor',
                   transformer_attention_weights_changed=True, deterministic_resume=True,
                   uninterrupted_steps=128, split_steps=[64,64], optimizer_steps=restored.optimizer_steps)
    (ROOT/'verification/artifacts/transformer.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt,indent=2))


if __name__ == '__main__':
    main()
