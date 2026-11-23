//! Task graph admission and scheduling. A node is one bounded agent job.
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum AgentKind {
    Model,
    Deterministic,
    Human,
    Api,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct TaskSpec {
    pub id: String,
    pub agent_id: String,
    pub agent_kind: AgentKind,
    pub capability: String,
    pub objective: String,
    #[serde(default)]
    pub depends_on: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TaskState {
    Pending,
    Running,
    WaitingUser,
    Completed,
    Failed,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct TaskRecord {
    pub spec: TaskSpec,
    pub state: TaskState,
    pub generation_count: Option<u8>,
}

pub type ParallelTaskResult = Vec<(String, Result<(), String>)>;

#[derive(Default)]
pub struct TaskGraph {
    tasks: BTreeMap<String, TaskRecord>,
}

impl TaskGraph {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn add_batch(&mut self, specs: Vec<TaskSpec>) -> Result<(), String> {
        if specs.is_empty() {
            return Err("empty task batch".into());
        }
        let mut ids: BTreeSet<String> = self.tasks.keys().cloned().collect();
        for spec in &specs {
            if spec.id.is_empty()
                || spec.agent_id.is_empty()
                || spec.capability.is_empty()
                || spec.objective.trim().is_empty()
                || !ids.insert(spec.id.clone())
            {
                return Err("invalid or duplicate task spec".into());
            }
        }
        for spec in &specs {
            let mut deps = BTreeSet::new();
            for parent in &spec.depends_on {
                if parent == &spec.id || !ids.contains(parent) || !deps.insert(parent) {
                    return Err(format!("invalid dependency for {}", spec.id));
                }
            }
        }
        let mut combined: BTreeMap<String, Vec<String>> = self
            .tasks
            .iter()
            .map(|(id, row)| (id.clone(), row.spec.depends_on.clone()))
            .collect();
        for spec in &specs {
            combined.insert(spec.id.clone(), spec.depends_on.clone());
        }
        let mut done = BTreeSet::new();
        loop {
            let mut advanced = false;
            for (id, deps) in &combined {
                if !done.contains(id) && deps.iter().all(|dep| done.contains(dep)) {
                    done.insert(id.clone());
                    advanced = true;
                }
            }
            if done.len() == combined.len() {
                break;
            }
            if !advanced {
                return Err("task graph contains a cycle".into());
            }
        }
        for spec in specs {
            self.tasks.insert(
                spec.id.clone(),
                TaskRecord {
                    spec,
                    state: TaskState::Pending,
                    generation_count: None,
                },
            );
        }
        Ok(())
    }

    pub fn ready(&self) -> Vec<String> {
        self.tasks
            .iter()
            .filter(|(_, row)| {
                row.state == TaskState::Pending
                    && row.spec.depends_on.iter().all(|parent| {
                        self.tasks
                            .get(parent)
                            .is_some_and(|p| p.state == TaskState::Completed)
                    })
            })
            .map(|(id, _)| id.clone())
            .collect()
    }

    pub fn claim(&mut self, id: &str) -> Result<TaskSpec, String> {
        if !self.ready().iter().any(|ready| ready == id) {
            return Err("task not ready for dispatch".into());
        }
        let row = self.tasks.get_mut(id).ok_or("unknown task")?;
        row.state = TaskState::Running;
        Ok(row.spec.clone())
    }

    pub fn complete(&mut self, id: &str, generation_count: u8) -> Result<(), String> {
        let row = self.tasks.get_mut(id).ok_or("unknown task")?;
        if row.state != TaskState::Running {
            return Err("task is not running".into());
        }
        let expected = if row.spec.agent_kind == AgentKind::Model {
            1
        } else {
            0
        };
        if generation_count != expected {
            return Err("agent generation count violates one-task contract".into());
        }
        row.state = TaskState::Completed;
        row.generation_count = Some(generation_count);
        Ok(())
    }

    pub fn wait_for_user(&mut self, id: &str) -> Result<(), String> {
        let row = self.tasks.get_mut(id).ok_or("unknown task")?;
        if row.state != TaskState::Running {
            return Err("task is not running".into());
        }
        row.state = TaskState::WaitingUser;
        Ok(())
    }

    pub fn resume_user(&mut self, id: &str) -> Result<(), String> {
        let row = self.tasks.get_mut(id).ok_or("unknown task")?;
        if row.state != TaskState::WaitingUser {
            return Err("task is not waiting for the user".into());
        }
        row.state = TaskState::Running;
        Ok(())
    }

    pub fn fail(&mut self, id: &str) -> Result<(), String> {
        let row = self.tasks.get_mut(id).ok_or("unknown task")?;
        if row.state != TaskState::Running {
            return Err("task is not running".into());
        }
        row.state = TaskState::Failed;
        Ok(())
    }

    pub fn records(&self) -> Vec<TaskRecord> {
        self.tasks.values().cloned().collect()
    }

    /// Dispatch all currently ready tasks concurrently, then commit results in Rust.
    /// A worker receives one immutable task spec and returns its generation count.
    pub fn run_ready_parallel<F>(&mut self, worker: F) -> Result<ParallelTaskResult, String>
    where
        F: Fn(TaskSpec) -> Result<u8, String> + Sync,
    {
        let ids = self.ready();
        let mut specs = Vec::with_capacity(ids.len());
        for id in ids {
            specs.push(self.claim(&id)?);
        }
        let outputs = std::thread::scope(|scope| {
            let handles: Vec<_> = specs
                .into_iter()
                .map(|spec| {
                    let id = spec.id.clone();
                    let handle = scope.spawn(|| worker(spec));
                    (id, handle)
                })
                .collect();
            handles
                .into_iter()
                .map(|(id, handle)| {
                    let result = handle
                        .join()
                        .unwrap_or_else(|_| Err("worker panicked".into()));
                    (id, result)
                })
                .collect::<Vec<_>>()
        });
        let mut committed = Vec::with_capacity(outputs.len());
        for (id, result) in outputs {
            let recorded = match result {
                Ok(count) => self.complete(&id, count),
                Err(error) => {
                    self.fail(&id)?;
                    Err(error)
                }
            };
            committed.push((id, recorded));
        }
        Ok(committed)
    }

    /// Execute the ready cohort serially when each worker loads a large model.
    /// The graph remains unchanged; this only caps simultaneous resource use.
    pub fn run_ready_sequential<F>(&mut self, worker: F) -> Result<ParallelTaskResult, String>
    where
        F: FnMut(TaskSpec) -> Result<u8, String>,
    {
        let mut worker = worker;
        let ids = self.ready();
        let mut committed = Vec::with_capacity(ids.len());
        for id in ids {
            let spec = self.claim(&id)?;
            let result = worker(spec);
            let recorded = match result {
                Ok(count) => self.complete(&id, count),
                Err(error) => {
                    self.fail(&id)?;
                    Err(error)
                }
            };
            committed.push((id, recorded));
        }
        Ok(committed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Barrier};

    fn task(id: &str, parents: &[&str], kind: AgentKind) -> TaskSpec {
        TaskSpec {
            id: id.into(),
            agent_id: id.into(),
            agent_kind: kind,
            capability: "bounded-task".into(),
            objective: format!("Do {id}"),
            depends_on: parents.iter().map(|p| (*p).into()).collect(),
        }
    }

    #[test]
    fn independent_tasks_are_ready_together_and_dependencies_gate_successors() {
        let mut g = TaskGraph::new();
        g.add_batch(vec![
            task("F", &["D", "E"], AgentKind::Deterministic),
            task("A", &[], AgentKind::Model),
            task("B", &[], AgentKind::Deterministic),
            task("C", &[], AgentKind::Api),
            task("D", &["A", "B"], AgentKind::Deterministic),
            task("E", &["C"], AgentKind::Deterministic),
        ])
        .unwrap();
        assert_eq!(g.ready(), ["A", "B", "C"]);
        g.claim("A").unwrap();
        assert!(g.complete("A", 0).is_err());
        g.complete("A", 1).unwrap();
        assert_eq!(g.ready(), ["B", "C"]);
        g.claim("B").unwrap();
        g.complete("B", 0).unwrap();
        assert_eq!(g.ready(), ["C", "D"]);
        g.claim("C").unwrap();
        g.complete("C", 0).unwrap();
        assert_eq!(g.ready(), ["D", "E"]);
        g.claim("D").unwrap();
        g.claim("E").unwrap();
        g.complete("E", 0).unwrap();
        g.complete("D", 0).unwrap();
        assert_eq!(g.ready(), ["F"]);
    }

    #[test]
    fn dynamic_plan_and_waiting_user_are_supported() {
        let mut g = TaskGraph::new();
        g.add_batch(vec![task("discover", &[], AgentKind::Deterministic)])
            .unwrap();
        g.claim("discover").unwrap();
        g.complete("discover", 0).unwrap();
        g.add_batch(vec![
            task("question", &["discover"], AgentKind::Human),
            task("work", &["question"], AgentKind::Model),
        ])
        .unwrap();
        g.claim("question").unwrap();
        g.wait_for_user("question").unwrap();
        assert!(g.ready().is_empty());
        g.resume_user("question").unwrap();
        g.complete("question", 0).unwrap();
        assert_eq!(g.ready(), ["work"]);
    }

    #[test]
    fn cycles_and_unknown_dependencies_are_rejected_without_partial_insert() {
        let mut g = TaskGraph::new();
        assert!(g
            .add_batch(vec![
                task("A", &["B"], AgentKind::Model),
                task("B", &["A"], AgentKind::Model)
            ])
            .is_err());
        assert!(g.records().is_empty());
        assert!(g
            .add_batch(vec![task("A", &["missing"], AgentKind::Model)])
            .is_err());
    }

    #[test]
    fn independent_work_runs_concurrently_before_dependent_work() {
        let mut g = TaskGraph::new();
        g.add_batch(vec![
            task("A", &[], AgentKind::Deterministic),
            task("B", &[], AgentKind::Deterministic),
            task("C", &[], AgentKind::Deterministic),
            task("F", &["A", "B", "C"], AgentKind::Deterministic),
        ])
        .unwrap();
        let barrier = Arc::new(Barrier::new(3));
        let results = g
            .run_ready_parallel(|spec| {
                barrier.wait(); // Deadlocks if A, B, C were dispatched serially.
                assert!(matches!(spec.id.as_str(), "A" | "B" | "C"));
                Ok(0)
            })
            .unwrap();
        assert_eq!(results.len(), 3);
        assert!(results.iter().all(|(_, result)| result.is_ok()));
        assert_eq!(g.ready(), ["F"]);
        let final_result = g
            .run_ready_parallel(|spec| {
                assert_eq!(spec.id, "F");
                Ok(0)
            })
            .unwrap();
        assert!(final_result[0].1.is_ok());
    }

    #[test]
    fn large_model_cohort_can_be_resource_capped_without_changing_dependencies() {
        let mut g = TaskGraph::new();
        g.add_batch(vec![
            task("A", &[], AgentKind::Model),
            task("B", &[], AgentKind::Model),
            task("C", &["A", "B"], AgentKind::Deterministic),
        ])
        .unwrap();
        let mut completed_order = Vec::new();
        let results = g
            .run_ready_sequential(|spec| {
                completed_order.push(spec.id);
                Ok(1)
            })
            .unwrap();
        assert_eq!(completed_order, ["A", "B"]);
        assert!(results.iter().all(|(_, result)| result.is_ok()));
        assert_eq!(g.ready(), ["C"]);
        let final_result = g
            .run_ready_sequential(|spec| {
                assert_eq!(spec.id, "C");
                Ok(0)
            })
            .unwrap();
        assert!(final_result[0].1.is_ok());
    }
}
