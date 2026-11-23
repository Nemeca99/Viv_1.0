// Verified Rust Monotonic Counter
// Solves E0596: Enforces mutable reference contract in Rust 1.90.0

pub struct MonotonicCounter {
    value: u64,
}

impl MonotonicCounter {
    pub fn new() -> Self {
        Self { value: 0 }
    }

    pub fn increment(&mut self) -> u64 {
        self.value += 1;
        self.value
    }

    pub fn get(&self) -> u64 {
        self.value
    }
}

fn main() {
    let mut c = MonotonicCounter::new();
    assert_eq!(c.get(), 0);
    assert_eq!(c.increment(), 1);
    assert_eq!(c.increment(), 2);
    assert_eq!(c.increment(), 3);
    assert_eq!(c.get(), 3);
    println!("FIB_PASS");
}
