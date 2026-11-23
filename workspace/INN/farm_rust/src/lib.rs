use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::ffi::{CStr, CString};
use std::os::raw::c_char;

const TOOLS: [&str; 8] = [
    "TILL", "SEED", "WATER", "HARVEST", "MERGE", "IDLE", "UPGRADE", "AUTOMATE",
];
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct Config {
    tills: u64,
    till_decay: u64,
    seed_decay: u64,
    water_decay: u64,
    harvest_duration: u64,
}
#[derive(Clone, Serialize, Deserialize)]
struct Plot {
    id: usize,
    active: u8,
    tier: u64,
    #[serde(rename = "yield")]
    yield_: u64,
    stage: String,
    tills: u64,
    water: u64,
    deadline: u64,
    timer: u64,
    last: u64,
    harvests: u64,
    coins: u64,
    decays: u64,
    reward: f64,
    urgency: f64,
    age: u64,
    queue: Vec<String>,
    upgrade: u64,
    auto: u8,
}
impl Plot {
    fn fresh(id: usize) -> Self {
        Self {
            id,
            active: 0,
            tier: 1,
            yield_: 1,
            stage: "BARREN".into(),
            tills: 0,
            water: 0,
            deadline: 0,
            timer: 0,
            last: 0,
            harvests: 0,
            coins: 0,
            decays: 0,
            reward: 0.,
            urgency: 0.,
            age: 0,
            queue: vec![],
            upgrade: 0,
            auto: 0,
        }
    }
    fn reset(&mut self, tick: u64, lose: bool) {
        self.stage = "BARREN".into();
        self.tills = 0;
        self.water = 0;
        self.deadline = 0;
        self.timer = 0;
        self.last = tick;
        self.age = 0;
        self.urgency = 0.;
        if lose {
            self.upgrade = 0;
            self.auto = 0;
        }
    }
    fn busy(&self) -> bool {
        matches!(self.stage.as_str(), "GROWING" | "HARVESTING")
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct Runtime {
    tick: u64,
    bank: f64,
    lifetime: f64,
    next: f64,
    active: usize,
    max: usize,
    harvests: u64,
    decays: u64,
    episode: f64,
    best: f64,
    last_tool: String,
    last_a: usize,
    last_b: usize,
    last_reward: f64,
    steps: u64,
    epsilon: f64,
    success: u64,
    invalid: u64,
    rng: u32,
}
#[derive(Clone, Serialize, Deserialize)]
struct Farm {
    config: Config,
    r: Runtime,
    p: Vec<Plot>,
    #[serde(skip)]
    begun: bool,
    #[serde(skip)]
    world_reward: f64,
}
impl Farm {
    fn new() -> Self {
        let mut p: Vec<_> = (1..=64).map(Plot::fresh).collect();
        p[0].active = 1;
        Self {
            config: Config {
                tills: 3,
                till_decay: 2,
                seed_decay: 2,
                water_decay: 2,
                harvest_duration: 2,
            },
            r: Runtime {
                tick: 0,
                bank: 0.,
                lifetime: 0.,
                next: 100.,
                active: 1,
                max: 1,
                harvests: 0,
                decays: 0,
                episode: 0.,
                best: 0.,
                last_tool: "NONE".into(),
                last_a: 0,
                last_b: 0,
                last_reward: 0.,
                steps: 0,
                epsilon: 0.25,
                success: 0,
                invalid: 0,
                rng: 1,
            },
            p,
            begun: false,
            world_reward: 0.,
        }
    }
    fn sync(&mut self) {
        self.r.active = self.p.iter().filter(|p| p.active != 0).count();
        self.r.max = self.r.max.max(self.r.active);
    }
    fn urgency(&self, p: &Plot) -> f64 {
        if p.active == 0 || p.auto != 0 || p.busy() {
            return 0.;
        }
        if p.stage == "BARREN" {
            return ((self.r.tick - p.last) as f64 / 2.).clamp(0., 1.);
        }
        let span = match p.stage.as_str() {
            "TILLED" => self.config.till_decay,
            "SEEDED" => self.config.seed_decay,
            _ => self.config.water_decay,
        };
        if p.deadline == 0 {
            0.
        } else {
            (1. - (p.deadline as f64 - self.r.tick as f64) / span as f64).clamp(0., 1.)
        }
    }
    fn upgrade_cost(&self, p: &Plot) -> f64 {
        (p.tier * 1000 * self.r.max as u64) as f64
    }
    fn merge_cost(&self) -> f64 {
        let n = self.p.iter().filter(|p| p.active != 0).count() as f64;
        let tier = self.p.iter().map(|p| p.tier).max().unwrap_or(1) as f64;
        (100. * (n + 1.) / n * tier).round()
    }
    fn legal(&self, t: &str, a: usize, b: usize) -> bool {
        if t == "IDLE" {
            return true;
        }
        let Some(p) = a.checked_sub(1).and_then(|i| self.p.get(i)) else {
            return false;
        };
        if p.active == 0 {
            return false;
        }
        match t {
            "TILL" => p.auto == 0 && p.stage == "BARREN",
            "SEED" => p.auto == 0 && p.stage == "TILLED",
            "WATER" => p.auto == 0 && matches!(p.stage.as_str(), "SEEDED" | "WATER1"),
            "HARVEST" => p.auto == 0 && p.stage == "WATER2",
            "UPGRADE" => {
                p.auto == 0
                    && p.queue.is_empty()
                    && p.upgrade < 3
                    && self.r.bank >= self.upgrade_cost(p)
            }
            "AUTOMATE" => p.auto == 0 && p.queue.is_empty() && p.upgrade == 3 && self.r.bank >= 1.,
            "MERGE" => b
                .checked_sub(1)
                .and_then(|i| self.p.get(i))
                .is_some_and(|q| {
                    q.active != 0
                        && q.id != p.id
                        && q.tier == p.tier
                        && p.queue.is_empty()
                        && q.queue.is_empty()
                        && !p.busy()
                        && !q.busy()
                        && self.r.bank >= self.merge_cost()
                }),
            _ => false,
        }
    }
    fn manual(&mut self, a: usize, t: &str) {
        let tick = self.r.tick;
        let p = &mut self.p[a - 1];
        p.last = tick;
        p.age = 0;
        match t {
            "TILL" => {
                p.tills += 1;
                if p.tills >= self.config.tills.saturating_sub(p.upgrade.min(2)).max(1) {
                    p.stage = "TILLED".into();
                    p.deadline = tick + self.config.till_decay;
                }
            }
            "SEED" => {
                p.stage = "SEEDED".into();
                p.deadline = tick + self.config.seed_decay;
            }
            "WATER" => {
                p.water += if p.upgrade >= 3 { 2 } else { 1 };
                if p.water >= 2 {
                    p.stage = "GROWING".into();
                    p.timer = tick + 2;
                    p.deadline = 0;
                } else {
                    p.stage = "WATER1".into();
                    p.deadline = tick + self.config.water_decay;
                }
            }
            "HARVEST" => {
                p.stage = "HARVESTING".into();
                p.timer = tick + self.config.harvest_duration;
                p.deadline = 0;
            }
            _ => (),
        }
    }
    fn begin(&mut self) -> Result<Value, String> {
        if self.begun {
            return Err("Tick already begun".into());
        }
        self.r.tick += 1;
        let tick = self.r.tick;
        let mut events = vec![];
        for p in self.p.iter_mut().filter(|p| p.active != 0) {
            if p.stage == "GROWING" && tick >= p.timer {
                p.stage = "WATER2".into();
                p.timer = 0;
                p.deadline = tick + self.config.water_decay;
            } else if p.stage == "HARVESTING" && tick >= p.timer {
                self.r.bank += p.yield_ as f64;
                self.r.lifetime += p.yield_ as f64;
                self.r.harvests += 1;
                p.harvests += 1;
                p.coins += p.yield_;
                events.push(json!({"kind":"COMPLETION","plot":p.id,"reward":p.yield_,"note":"Harvest proceeds"}));
                p.reset(tick, false);
            }
        }
        for p in self.p.iter_mut().filter(|p| p.active != 0) {
            if p.deadline != 0 && tick > p.deadline {
                p.decays += 1;
                self.r.decays += 1;
                events.push(
                    json!({"kind":"DECAY","plot":p.id,"reward":-0.6,"note":"Missed deadline"}),
                );
                p.reset(tick, false);
            }
        }
        let mut automated: Vec<_> = self
            .p
            .iter()
            .filter(|p| p.active != 0 && p.auto != 0)
            .map(|p| p.id)
            .collect();
        if !automated.is_empty() {
            let n = tick as usize % automated.len();
            automated.rotate_left(n);
        }
        for a in automated {
            if self.p[a - 1].busy() {
                continue;
            }
            if self.r.bank < 1. {
                let p = &mut self.p[a - 1];
                p.decays += 1;
                self.r.decays += 1;
                events.push(json!({"kind":"AUTO_FAILURE","plot":a,"reward":-0.6,"note":"Cannot pay; automation and upgrades lost"}));
                p.reset(tick, true);
                continue;
            }
            let t = match self.p[a - 1].stage.as_str() {
                "BARREN" => "TILL",
                "TILLED" => "SEED",
                "WATER2" => "HARVEST",
                _ => "WATER",
            };
            self.r.bank -= 1.;
            events.push(json!({"kind":"AUTO_COST","plot":a,"reward":-1.,"note":t}));
            self.manual(a, t);
        }
        for i in 0..self.p.len() {
            if self.p[i].active == 0 {
                continue;
            }
            let age = tick - self.p[i].last;
            self.p[i].age = age;
            if self.p[i].stage == "BARREN" && age > 2 && self.p[i].auto == 0 {
                if self.r.bank > 0. {
                    self.r.bank -= 1.;
                    events.push(json!({"kind":"DRAIN","plot":i+1,"reward":-1.,"note":"Barren resource drain"}));
                } else if self.p.iter().filter(|p| p.active != 0).count() > 1 {
                    self.p[i].active = 0;
                    events.push(json!({"kind":"PLOT_LOSS","plot":i+1,"reward":-1.,"note":"Barren plot bankruptcy"}));
                }
            }
            self.p[i].urgency = self.urgency(&self.p[i]);
        }
        self.sync();
        while self.r.bank >= self.r.next {
            let Some(i) = self.p.iter().position(|p| p.active == 0) else {
                break;
            };
            let p = &mut self.p[i];
            p.active = 1;
            p.tier = 1;
            p.yield_ = 1;
            p.reset(tick, true);
            self.sync();
            self.r.next += 100. + self.r.active.saturating_sub(1) as f64;
            events
                .push(json!({"kind":"EXPANSION","plot":i+1,"reward":0.,"note":"New tier-1 plot"}));
        }
        self.world_reward = events.iter().map(|e| e["reward"].as_f64().unwrap()).sum();
        self.begun = true;
        Ok(
            json!({"events":events,"world_reward":self.world_reward,"r":self.r,"candidates":self.candidates()}),
        )
    }
    fn candidate(&self, t: &str, a: usize, b: usize, queued: bool) -> Value {
        let n = self.r.active as f64;
        let u = self
            .p
            .iter()
            .filter(|p| p.active != 0 && p.auto == 0)
            .map(|p| self.urgency(p))
            .fold(0., f64::max);
        let p = a.checked_sub(1).and_then(|i| self.p.get(i));
        let (urgency, progress, yield_n) = if t == "IDLE" {
            (
                1. - u,
                self.p.iter().filter(|p| p.active != 0 && p.busy()).count() as f64 / n,
                0.,
            )
        } else {
            let p = p.unwrap();
            match t {
                "MERGE" => (
                    (self.urgency(p) + self.urgency(&self.p[b - 1])) / 2.,
                    0.5,
                    ((p.yield_ + self.p[b - 1].yield_) as f64 / 20.).clamp(0., 1.),
                ),
                "UPGRADE" | "AUTOMATE" => (
                    self.urgency(p),
                    p.upgrade as f64 / 3.,
                    (p.yield_ as f64 / 10.).clamp(0., 1.),
                ),
                _ => (
                    self.urgency(p),
                    match p.stage.as_str() {
                        "BARREN" => 0.1 + 0.1 * p.tills as f64,
                        "TILLED" => 0.35,
                        "SEEDED" => 0.5,
                        "WATER1" => 0.65,
                        "GROWING" => 0.75,
                        "WATER2" => 0.85,
                        _ => 0.95,
                    },
                    (p.yield_ as f64 / 10.).clamp(0., 1.),
                ),
            }
        };
        let bank = if matches!(t, "MERGE" | "UPGRADE" | "AUTOMATE") {
            (self.r.bank
                / (if t == "UPGRADE" {
                    self.upgrade_cost(p.unwrap())
                } else {
                    self.merge_cost()
                })
                .max(1.))
            .clamp(0., 1.)
        } else {
            0.
        };
        json!({"t":t,"a":a,"b":b,"stage":p.map_or("GLOBAL",|p|p.stage.as_str()),"queued":queued,"active":p.is_none_or(|p|p.active!=0),"x":[urgency*(1.+u),progress,yield_n,(n/12.).clamp(0.,1.),bank]})
    }
    fn candidates(&self) -> Vec<Value> {
        let mut out = vec![];
        for p in self
            .p
            .iter()
            .filter(|p| p.active == 0 && !p.queue.is_empty())
        {
            out.push(self.candidate(&p.queue[0], p.id, 0, true));
        }
        let active: Vec<_> = self.p.iter().filter(|p| p.active != 0).collect();
        for p in &active {
            if p.auto == 0 && !p.busy() {
                if let Some(t) = p.queue.first() {
                    out.push(self.candidate(t, p.id, 0, true));
                } else {
                    for t in &TOOLS[..4] {
                        out.push(self.candidate(t, p.id, 0, false));
                    }
                }
            }
            for t in ["UPGRADE", "AUTOMATE"] {
                if self.legal(t, p.id, 0) {
                    out.push(self.candidate(t, p.id, 0, false));
                }
            }
        }
        for (i, p) in active.iter().enumerate() {
            for q in &active[i + 1..] {
                if self.legal("MERGE", p.id, q.id) {
                    out.push(self.candidate("MERGE", p.id, q.id, false));
                }
            }
        }
        out.push(self.candidate("IDLE", 0, 0, false));
        out
    }
    fn execute(&mut self, v: &Value) -> Result<Value, String> {
        if !self.begun {
            return Err("Begin tick before executing".into());
        }
        let t = v["t"].as_str().ok_or("Missing tool")?;
        if !TOOLS.contains(&t) {
            return Err("Unknown tool".into());
        }
        let a = v["a"].as_u64().unwrap_or(0) as usize;
        let b = v["b"].as_u64().unwrap_or(0) as usize;
        if a > 64 || b > 64 {
            return Err("Plot out of range".into());
        }
        let queued = v["queued"].as_bool().unwrap_or(false);
        if queued {
            if a == 0 || self.p[a - 1].queue.first().map(String::as_str) != Some(t) {
                return Err("FIFO head changed".into());
            }
            self.p[a - 1].queue.remove(0);
        } else if TOOLS[..4].contains(&t) {
            if a == 0 {
                return Err("Missing plot".into());
            }
            let sequence: Vec<String> = serde_json::from_value(v["commitment"].clone())
                .map_err(|_| "Missing commitment")?;
            if sequence.is_empty()
                || sequence.len() > 4
                || sequence[0] != t
                || sequence.iter().any(|t| !TOOLS[..4].contains(&t.as_str()))
                || !self.p[a - 1].queue.is_empty()
            {
                return Err("Invalid commitment".into());
            }
            self.p[a - 1].queue = sequence;
            self.p[a - 1].queue.remove(0);
        }
        let legal = self.legal(t, a, b);
        let passed = v["gate"].as_f64().ok_or("Missing gate")?
            >= v["threshold"].as_f64().ok_or("Missing threshold")?;
        let executed = legal && passed;
        let reward = if !executed {
            if a > 0 && self.p[a - 1].stage == "BARREN" {
                -1.
            } else {
                -0.6
            }
        } else {
            match t {
                "TILL" | "SEED" | "WATER" | "HARVEST" => {
                    self.manual(a, t);
                    0.
                }
                "UPGRADE" => {
                    let cost = self.upgrade_cost(&self.p[a - 1]);
                    self.r.bank -= cost;
                    self.p[a - 1].upgrade += 1;
                    -cost
                }
                "AUTOMATE" => {
                    self.p[a - 1].auto = 1;
                    0.
                }
                "MERGE" => {
                    let cost = self.merge_cost();
                    self.r.bank -= cost;
                    self.p[a - 1].tier += 1;
                    self.p[a - 1].yield_ = self.p[a - 1].tier;
                    self.p[a - 1].reset(self.r.tick, true);
                    self.p[b - 1].active = 0;
                    self.p[b - 1].reset(self.r.tick, true);
                    self.sync();
                    -cost
                }
                _ => 0.,
            }
        };
        if executed && a > 0 {
            self.p[a - 1].reward = reward;
        }
        self.r.episode += self.world_reward + reward;
        self.r.best = self.r.best.max(self.r.episode);
        self.r.last_tool = t.into();
        self.r.last_a = a;
        self.r.last_b = b;
        self.r.last_reward = self.world_reward + reward;
        self.r.steps += 1;
        if executed {
            self.r.success += 1;
        } else {
            self.r.invalid += 1;
        }
        self.begun = false;
        self.sync();
        self.validate()?;
        Ok(
            json!({"legal":legal,"executed":executed,"reward":reward,"note":if executed{"EXECUTED"}else if !passed{"B1_DENIED"}else{"RULE_DENIED"},"r":self.r}),
        )
    }
    fn preview(&self, v: &Value) -> Result<Value, String> {
        let a = v["a"].as_u64().ok_or("Missing plot")? as usize;
        if !(1..=64).contains(&a) {
            return Err("Plot out of range".into());
        }
        let sequence: Vec<String> =
            serde_json::from_value(v["sequence"].clone()).map_err(|_| "Invalid sequence")?;
        let mut sim = self.clone();
        sim.p[a - 1].queue.clear();
        for t in sequence {
            if !TOOLS[..4].contains(&t.as_str()) {
                return Err("Invalid planning tool".into());
            }
            if sim.legal(&t, a, 0) {
                sim.manual(a, &t);
            }
            sim.r.tick += 1;
            if sim.p[a - 1].busy() {
                sim.r.tick = sim.r.tick.max(sim.p[a - 1].timer);
                if sim.p[a - 1].stage == "GROWING" {
                    sim.p[a - 1].stage = "WATER2".into();
                    sim.p[a - 1].timer = 0;
                    sim.p[a - 1].deadline = sim.r.tick + sim.config.water_decay;
                } else {
                    sim.p[a - 1].reset(sim.r.tick, false);
                }
            }
            if sim.p[a - 1].deadline != 0 && sim.r.tick > sim.p[a - 1].deadline {
                sim.p[a - 1].reset(sim.r.tick, false);
            }
        }
        Ok(
            json!({"tick":sim.r.tick,"candidates":TOOLS[..4].iter().map(|t|sim.candidate(t,a,0,false)).collect::<Vec<_>>()}),
        )
    }
    fn validate(&self) -> Result<(), String> {
        if self.p.len() != 64
            || self.r.active == 0
            || self.r.active != self.p.iter().filter(|p| p.active != 0).count()
            || self.r.max < self.r.active
            || self.r.max > 64
            || !self.r.bank.is_finite()
            || self.r.bank < 0.
            || !self.r.episode.is_finite()
        {
            return Err("Farm invariant failed".into());
        }
        for (i, p) in self.p.iter().enumerate() {
            if p.id != i + 1
                || p.queue.len() > 4
                || p.queue.iter().any(|t| !TOOLS[..4].contains(&t.as_str()))
                || p.upgrade > 3
                || (p.auto != 0 && p.upgrade != 3)
                || !matches!(
                    p.stage.as_str(),
                    "BARREN" | "TILLED" | "SEEDED" | "WATER1" | "GROWING" | "WATER2" | "HARVESTING"
                )
            {
                return Err("Plot invariant failed".into());
            }
        }
        if self.config.tills != 3
            || [
                self.config.till_decay,
                self.config.seed_decay,
                self.config.water_decay,
                self.config.harvest_duration,
            ]
            .contains(&0)
        {
            return Err("Invalid farm configuration".into());
        }
        Ok(())
    }
    fn request(&mut self, v: Value) -> Result<Value, String> {
        match v["op"].as_str().unwrap_or("") {
            "load" => {
                let next: Farm =
                    serde_json::from_value(v["state"].clone()).map_err(|e| e.to_string())?;
                next.validate()?;
                *self = next;
                Ok(json!({"loaded":true}))
            }
            "state" => Ok(json!({"config":self.config,"r":self.r,"p":self.p})),
            "begin" => self.begin(),
            "candidates" => Ok(json!(self.candidates())),
            "execute" => self.execute(&v),
            "preview" => self.preview(&v),
            _ => Err("Unknown operation".into()),
        }
    }
}

#[no_mangle]
pub extern "C" fn farm_new() -> *mut std::ffi::c_void {
    Box::into_raw(Box::new(Farm::new())).cast()
}
#[no_mangle]
pub unsafe extern "C" fn farm_drop(handle: *mut std::ffi::c_void) {
    if !handle.is_null() {
        drop(Box::from_raw(handle.cast::<Farm>()));
    }
}
#[no_mangle]
pub unsafe extern "C" fn farm_request(
    handle: *mut std::ffi::c_void,
    input: *const c_char,
) -> *mut c_char {
    let response = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        if handle.is_null() || input.is_null() {
            return json!({"error":"Null pointer"});
        }
        let request = serde_json::from_slice(CStr::from_ptr(input).to_bytes());
        match request {
            Ok(v) => match (&mut *handle.cast::<Farm>()).request(v) {
                Ok(result) => json!({"result":result}),
                Err(error) => json!({"error":error}),
            },
            Err(e) => json!({"error":e.to_string()}),
        }
    }))
    .unwrap_or_else(|_| json!({"error":"Rust farm panic"}));
    CString::new(response.to_string()).unwrap().into_raw()
}
#[no_mangle]
pub unsafe extern "C" fn farm_free(text: *mut c_char) {
    if !text.is_null() {
        drop(CString::from_raw(text));
    }
}
