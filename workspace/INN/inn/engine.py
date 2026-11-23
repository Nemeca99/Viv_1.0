import copy
import math
import random
from collections import deque
from datetime import datetime, timezone

TOOLS = ['TILL', 'SEED', 'WATER', 'HARVEST', 'MERGE', 'IDLE', 'UPGRADE', 'AUTOMATE']
STAGES = ['BARREN', 'TILLED', 'SEEDED', 'WATER1', 'WATER2', 'HARVESTING']
DEFAULT_CONFIG = dict(tickMs=1000, tills=3, tillDecay=2, seedDecay=2,
                      waterDecay=2, harvestDuration=2, alpha=.15, gamma=.9,
                      epsilonStart=.25, epsilonDecay=.999, epsilonMin=.02,
                      threshold=.5, surface=2, volumeFixed=None, dk=5)
LOG_HEADER = ['RUN ID','TICK','TOOL','PLOT A','PLOT B','STATE BEFORE','VALID','REWARD',
              'BANK','LIFETIME','ACTIVE PLOTS','DECAYS','EPSILON','QK RAW','F2 PROB','B1 GATE',
              'FINAL SCORE','X1','X2','X3','X4','X5','PHASE','VERSION','NEXT CANDIDATES',
              'IMMEDIATE REWARD','WORLD REWARD','LEGAL','EXECUTED','F1 PROB','NOTE']


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
        span = c['epsilonStart'] - c['epsilonMin']
        if abs(span) < 1e-12:
            ratio = 1.0  # UML <!0, !0> unity snap
        else:
            ratio = (c['epsilonStart'] - epsilon) / span
        value = min(3, max(1, 1 + 2 * ratio))
        return math.floor(value * 100 + .5) / 100

    def score(self, items, epsilon):
        divisor = (math.sqrt(self.config['dk']) ** self.config['surface']) if self.config['dk'] > 0 else 1.0
        if abs(divisor) < 1e-12 or not math.isfinite(divisor):
            divisor = 1.0  # UML <!0, !0> unity snap
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
        if not math.isfinite(delta):
            delta = 0.0  # UML {!0, !0} floor snap
        denom = 1 + sum(v * v for v in action['x'])
        rate = (self.config['alpha'] / denom) if (math.isfinite(denom) and denom > 1e-12) else self.config['alpha']
        w['b'] += rate * delta
        w['x'] = [v + rate * delta * x for v, x in zip(w['x'], action['x'])]
        w['n'] += 1
        w['delta'] = delta
        self.loss = .5 * delta * delta
        self.updates += 1
        if not math.isfinite(self.loss):
            self.loss = 0.0

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
        self.id = state.get('id') or 'RUN8-LOCAL-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        self.source = copy.deepcopy(state.get('source'))
        self.frontier = copy.deepcopy(state.get('frontier', {}))
        self.replayed = state.get('replayed', 0)
        self.log_next = state.get('logNext', 101)
        self.batch_start = state.get('batchStart', self.log_next)
        self.batch = copy.deepcopy(state.get('batch', []))
        self.last_action = state.get('lastAction')
        self.history = deque(copy.deepcopy(state.get('history', [])), maxlen=2048)

    def row(self, action, phase, reward, **extra):
        import json
        a = action or dict(t='WORLD',a=0,b=0,stage='GLOBAL',x=[0]*5,raw=0,f2=0,gate=0,score=0,f1=0)
        r = self.r
        return [self.id,extra.get('tick',r['tick']),a['t'],a['a'],a['b'],a['stage'],
                int(extra.get('executed',False)),reward,r['bank'],r['lifetime'],r['active'],
                r['decays'],r['epsilon'],a['raw'],a['f2'],a['gate'],a['score'],*a['x'],phase,
                '8-outcomes',json.dumps(extra['next'],separators=(',',':')) if 'next' in extra else '',
                extra.get('immediate',0),extra.get('world',0),int(extra.get('legal',False)),
                int(extra.get('executed',False)),a['f1'],extra.get('note','')]

    def commit_rows(self, rows):
        for row in rows:
            if row[22] == 'TRANSITION':
                for stage in (row[5], 'OVERALL'):
                    old = self.frontier.get(stage)
                    if old is None or row[7] > old[1]:
                        self.frontier[stage] = [row[2],row[7],row[1],self.r['max'],self.id]
        self.batch_start = self.log_next
        self.batch = rows
        self.log_next += len(rows)
        self.history.extend(copy.deepcopy(rows))

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
        rows = []
        if self.pending:
            p = self.pending
            reward = p['reward'] + observation['world_reward']
            next_items = self.next_items(items)
            self.engine.learn(p['a'], reward, next_items,
                              dict(items=p.get('context') or [p['a']], legal=p['legal']))
            transition = dict(tick=p['tick'], reward=reward, immediate=p['reward'],
                              world=observation['world_reward'], legal=p['legal'],
                              executed=p['executed'], action=p['a'])
            rows.append(self.row(p['a'],'TRANSITION',reward,tick=p['tick'],
                        next=[[TOOLS.index(a['t']),*a['x']] for a in next_items],
                        immediate=p['reward'],world=observation['world_reward'],
                        legal=p['legal'],executed=p['executed'],note='Next state at tick '+str(self.r['tick'])))
        for event in observation['events']:
            a = dict(t='HARVEST' if event['kind']=='COMPLETION' else 'WORLD',a=event['plot'],b=0,
                     stage='HARVESTING' if event['kind']=='COMPLETION' else 'WORLD',
                     x=[0]*5,raw=0,f1=0,f2=0,gate=0,score=0)
            rows.append(self.row(a,event['kind'],event['reward'],note=event['note']))
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
        self.r.update(rng=rng, epsilon=epsilon)
        rows.append(self.row(action,'ACTION',result['reward'],immediate=result['reward'],
                             legal=result['legal'],executed=result['executed'],note=result['note']))
        self.last_action = rows[-1]
        self.r['epsilon'] = max(self.engine.config['epsilonMin'],epsilon*self.engine.config['epsilonDecay'])
        self.pending = dict(a=action, reward=result['reward'], legal=result['legal'],
                            executed=result['executed'], tick=self.r['tick'], context=context)
        self.last_candidates = sorted(items, key=lambda a: a['score'], reverse=True)[:32]
        self.commit_rows(rows)
        return dict(tick=self.r['tick'], action=action, outcome=result, transition=transition,
                    events=observation['events'],rows=rows)

    def snapshot(self):
        state = self.farm.call('state')
        state.update(version='8-outcomes', config=self.engine.config, r=self.r,
                     pending=self.pending, lastCandidates=self.last_candidates,
                     engine_kind=self.engine.kind, **self.engine.state())
        state.update(id=self.id,source=self.source,frontier=self.frontier,replayed=self.replayed,
                     logNext=self.log_next,batchStart=self.batch_start,batch=self.batch,lastAction=self.last_action,
                     history=list(self.history))
        return state

    def set_bank(self, amount):
        value = float(amount)
        if not math.isfinite(value) or value < 0:
            raise ValueError('Bank amount must be finite and nonnegative')
        state = self.snapshot()
        state['r']['bank'] = value
        self.farm.call('load', state=state)
        self.r['bank'] = value

    def reset(self, history, seed):
        if self.engine.kind == 'transformer':
            raise ValueError('Source reset/replay requires the source engine')
        emitted = []
        if self.pending:
            p = self.pending
            self.engine.learn(p['a'],p['reward'],[])
            row = self.row(p['a'],'TRANSITION',p['reward'],tick=p['tick'],next=[],
                           immediate=p['reward'],legal=p['legal'],executed=p['executed'],
                           note='Terminal transition: user reset.')
            self.commit_rows([row])
            emitted.append(row)
            history = [*history,row]
        config = self.engine.config
        self.engine = type(self.engine)(config)
        from .farm import Farm
        with Farm() as new_farm:
            fresh = new_farm.call('state')
        fresh['config'] = config
        fresh['r'].update(rng=(int(seed)&0xffffffff) or 1,epsilon=config['epsilonStart'])
        self.farm.call('load',state=fresh)
        self.r = fresh['r']
        self.pending = None
        self.last_candidates = []
        self.last_action = None
        self.id = 'RUN8-LOCAL-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        self.replayed = 0
        self.replay(history)
        row = self.row(None,'RESET',0,note='New game; retained corpus and replayed compatible transitions.')
        self.commit_rows([row])
        emitted.append(row)
        return emitted

    def replay(self, history):
        import json
        rows = [r for r in history[-2048:] if r[23]=='8-outcomes' and r[22]=='TRANSITION'][-128:]
        for row in rows:
            x = row[17:22]
            next_vectors = json.loads(row[24] or '[]')
            if row[2] not in TOOLS or row[27] not in (0,1) or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in [row[7],*x]):
                raise ValueError('Invalid source replay record')
            if not isinstance(next_vectors,list) or any(len(v)!=6 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in v) or int(v[0])!=v[0] or not 0<=v[0]<8 for v in next_vectors):
                raise ValueError('Invalid next-action replay features')
            self.engine.learn(dict(t=row[2],x=x),row[7],[dict(t=TOOLS[int(v[0])],x=v[1:]) for v in next_vectors])
            self.engine.outcome(dict(stage=row[5],t=row[2]),bool(row[27]))
            self.replayed += 1


class SourceEngine(LinearEngine):
    """The supplied FarmScript's F1/F2/B1 engine, with its original updates."""
    kind = 'source-v8'


class StabilizedSourceEngine(SourceEngine):
    """Source learner with a conservative TD rate for behavioral training."""
    kind = 'learned-v9'

    def learn(self, action, reward, next_items, context=None):
        original = self.config['alpha']
        self.config['alpha'] = self.config.get('learningAlpha', 0.01)
        try:
            super().learn(action, reward, next_items, context)
        finally:
            self.config['alpha'] = original
