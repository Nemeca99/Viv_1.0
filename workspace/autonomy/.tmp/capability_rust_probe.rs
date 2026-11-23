pub fn fib(n:u32)->u64{match n{0=>0,1=>1,n=>fib(n-1)+fib(n-2)}}
#[cfg(test)]mod t{use super::*;#[test]fn proof(){assert_eq!(fib(10),55);}}
fn main(){assert_eq!(fib(10),55);}
