import copy
import math
import random

TOOLS = ['TILL', 'SEED', 'WATER', 'HARVEST', 'MERGE', 'IDLE', 'UPGRADE', 'AUTOMATE']
STAGES = ['BARREN', 'TILLED', 'SEEDED', 'WATER1', 'WATER2', 'HARVESTING']
DEFAULT_CONFIG = dict(tickMs=1000, tills=3, tillDecay=2, seedDecay=2,
                      waterDecay=2, harvestDuration=2, alpha=.15, gamma=.9,
                      epsilonStart=.25, epsilonDecay=.999, epsilonMin=.02,
                      threshold=.5, surface=2, volumeFixed=None, dk=5)


def sigmoid(x):
    return 1 / (1 + math.exp(-x)) if x >= 0 else math.exp(x) / (1 + math.exp(x))


def softmax(values):
    if not values:
        return []
    maximum = max(values)
    exps = [math.exp(v - maximum) for v in values]
    total = sum(exps)
    return [v / total for v in exps]


class LinearEngine:
    """Faithful Apps Script V8 learner, retained as a reference engine."""

    kind = 'linear-v8'

    def __init__(self, config, state=None):
        state = state or {}
        self.config = config
        self.w = copy.deepcopy(state.get('w', [dict(b=0., x=[0.] * 5, n=0, delta=0.) for _ in TOOLS]))
        self.validity = copy.deepcopy(state.get('validity', [[0.] * 6 for _ in STAGES]))
        self.loss = state.get('loss', 0.)
        self.updates = state.get('updates', 0)

    def raw(self, action):
        w = self.w[TOOLS.index(action['t'])]
        return w['b'] + sum(v * x for v, x in zip(w['x'], action['x']))

    def volume(self, epsilon):
        c = self.config
        if c['volumeFixed'] is not None:
            return c['volumeFixed']
        if c['epsilonStart'] == c['epsilonMin']:
            return 3
        value = min(3, max(1, 1 + 2 * (c['epsilonStart'] - epsilon) / (c['epsilonStart'] - c['epsilonMin'])))
        return math.floor(value * 100 + .5) / 100

    def score(self, items, epsilon):
        divisor = math.sqrt(self.config['dk']) ** self.config['surface']
        logits = [self.raw(a) / divisor for a in items]
        f1, f2 = softmax(logits), softmax([v * self.volume(epsilon) for v in logits])
        for i, a in enumerate(items):
            s = STAGES.index(a['stage']) if a['stage'] in STAGES else -1
            t = TOOLS.index(a['t'])
            gate = sigmoid(self.validity[s][t]) if s >= 0 and t < 4 else 1.
            a.update(raw=self.raw(a), f1=f1[i], f2=f2[i], gate=gate,
                     score=f2[i] if gate >= self.config['threshold'] else 0.)
        return items

    def learn(self, action, reward, next_items, context=None):
        future = max((self.raw(a) for a in next_items), default=0.)
        w = self.w[TOOLS.index(action['t'])]
        delta = reward + self.config['gamma'] * future - self.raw(action)
        rate = self.config['alpha'] / (1 + sum(v * v for v in action['x']))
        w['b'] += rate * delta
        w['x'] = [v + rate * delta * x for v, x in zip(w['x'], action['x'])]
        w['n'] += 1
        w['delta'] = delta
        self.loss = .5 * delta * delta
        self.updates += 1
        if not math.isfinite(self.loss):
            raise RuntimeError('Non-finite TD loss')

    def outcome(self, action, legal):
        if action['stage'] in STAGES and TOOLS.index(action['t']) < 4:
            s, t = STAGES.index(action['stage']), TOOLS.index(action['t'])
            z = self.validity[s][t]
            self.validity[s][t] = min(30., max(-30., z + self.config['alpha'] * (int(legal) - sigmoid(z))))

    def state(self):
        return dict(w=self.w, validity=self.validity, loss=self.loss, updates=self.updates)


class Simulation:
    def __init__(self, farm, engine, state=None, seed=1):
        self.farm, self.engine = farm, engine
        state = state or {}
        self.r = copy.deepcopy(state.get('r', farm.call('state')['r']))
        self.r['rng'] = self.r.get('rng', seed) if state else (seed & 0xffffffff) or 1
        self.pending = copy.deepcopy(state.get('pending'))
        self.last_candidates = []

    def random(self):
        x = self.r['rng']
        x ^= (x << 13) & 0xffffffff
        x ^= x >> 17
        x ^= (x << 5) & 0xffffffff
        self.r['rng'] = x & 0xffffffff
        return self.r['rng'] / 4294967296

    def choose(self, items, tick=None):
        tick = self.r['tick'] if tick is None else tick
        threshold = self.engine.config['threshold']
        queued = [a for a in items if a.get('queued')]
        if queued:
            denied = [a for a in queued if a['gate'] < threshold or not a['active']]
            if denied:
                return denied[(tick - 1) % len(denied)]
            allowed = [a for a in queued if a['gate'] >= threshold]
        else:
            allowed = [a for a in items if a['gate'] >= threshold]
        if not allowed:
            raise RuntimeError('No admitted action')
        if self.random() < self.r['epsilon']:
            return allowed[int(self.random() * len(allowed))]
        maximum = max(a['score'] for a in allowed)
        pool = [a for a in allowed if a['score'] == maximum]
        return pool[int(self.random() * len(pool))]

    def plan(self, action):
        sequence = [action['t']]
        while len(sequence) < 4:
            preview = self.farm.call('preview', a=action['a'], sequence=sequence)
            items = self.engine.score(preview['candidates'], self.r['epsilon'])
            allowed = [a for a in items if a['gate'] >= self.engine.config['threshold']]
            if not allowed:
                break
            sequence.append(self.choose(allowed, preview['tick'])['t'])
        return sequence

    def next_items(self, items):
        threshold = self.engine.config['threshold']
        denied = [a for a in items if a.get('queued') and (a['gate'] < threshold or not a['active'])]
        if denied:
            return [denied[(self.r['tick'] - 1) % len(denied)]]
        if self.engine.kind == 'transformer':
            # Plot identities and surrounding attention tokens can change neural values.
            return [a for a in items if a['gate'] >= threshold]
        unique = {}
        for a in items:
            if a['gate'] >= threshold:
                unique[(a['t'], *a['x'])] = a
        return list(unique.values())

    def step(self):
        epsilon, rng = self.r['epsilon'], self.r['rng']
        observation = self.farm.call('begin')
        self.r = observation['r']
        self.r.update(epsilon=epsilon, rng=rng)
        items = self.engine.score(observation['candidates'], epsilon)
        transition = None
        if self.pending:
            p = self.pending
            reward = p['reward'] + observation['world_reward']
            self.engine.learn(p['a'], reward, self.next_items(items),
                              dict(items=p.get('context') or [p['a']], legal=p['legal']))
            transition = dict(tick=p['tick'], reward=reward, immediate=p['reward'],
                              world=observation['world_reward'], legal=p['legal'],
                              executed=p['executed'], action=p['a'])
        items = self.engine.score(self.farm.call('candidates'), epsilon)
        action = copy.deepcopy(self.choose(items))
        context = copy.deepcopy(items)
        commitment = self.plan(action) if action['t'] in TOOLS[:4] and not action['queued'] else None
        request = dict(action, threshold=self.engine.config['threshold'])
        if commitment is not None:
            request['commitment'] = commitment
        result = self.farm.call('execute', **request)
        self.engine.outcome(action, result['legal'])
        rng = self.r['rng']
        self.r = result['r']
        self.r.update(rng=rng, epsilon=max(self.engine.config['epsilonMin'], epsilon * self.engine.config['epsilonDecay']))
        self.pending = dict(a=action, reward=result['reward'], legal=result['legal'],
                            executed=result['executed'], tick=self.r['tick'], context=context)
        self.last_candidates = sorted(items, key=lambda a: a['score'], reverse=True)[:32]
        return dict(tick=self.r['tick'], action=action, outcome=result, transition=transition,
                    events=observation['events'])

    def snapshot(self):
        state = self.farm.call('state')
        state.update(version='8-outcomes', config=self.engine.config, r=self.r,
                     pending=self.pending, lastCandidates=self.last_candidates,
                     engine_kind=self.engine.kind, **self.engine.state())
        return state
