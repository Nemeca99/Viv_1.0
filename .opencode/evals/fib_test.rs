pub fn fib(n: u32) -> u64 {
    let mut a = 0;
    let mut b = 1;
    for _ in 0..n {
        let c = a + b;
        a = b;
        b = c;
    }
    a
}

fn main() {
    let expected = [0u64, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89];
    for (n, &exp) in expected.iter().enumerate() {
        let got = fib(n as u32);
        assert_eq!(got, exp, "fib({n}) = {got}, expected {exp}");
        println!("fib({n}) = {got}");
    }
}
