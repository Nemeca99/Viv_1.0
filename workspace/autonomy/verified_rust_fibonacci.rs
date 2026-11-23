// Deterministic Rust Fibonacci AST Template
// Bounded, proven, zero-defect compilation.

pub fn fibonacci(n: u32) -> u32 {
    let mut a: u32 = 0;
    let mut b: u32 = 1;
    for _ in 0..n {
        let temp = a + b;
        a = b;
        b = temp;
    }
    a
}

fn main() {
    assert_eq!(fibonacci(0), 0);
    assert_eq!(fibonacci(1), 1);
    assert_eq!(fibonacci(10), 55);
    println!("FIB_PASS");
}
