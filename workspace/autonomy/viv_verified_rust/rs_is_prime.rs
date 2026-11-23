pub fn is_prime(n: u64) -> bool {
    if n <= 1 {
        return false;
    }

    let mut i = 2;
    while i * i <= n {
        if n % i == 0 {
            return false;
        }
        i += 1;
    }

    true
}
