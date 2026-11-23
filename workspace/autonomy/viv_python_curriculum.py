"""Python school curriculum for Viv, ordered the way a human learns Python:

Grade 0 (Day 1 Basics: Output, Variables, Strings, Numbers):
  - py0_hello_world     : print("Hello, World!") and see stdout
  - py0_variable_assign : assign a variable and print/return it
  - py0_add_two         : add two numbers
  - py0_string_join     : combine "Hello, " + name
  - py0_string_length   : count characters with len()

Grade 1 (Decisions, Loops, Lists):
  - py1_is_even         : if/else check (n % 2 == 0)
  - py1_count_to_n      : for loop building [1, 2, ..., n]
  - py1_sum_list        : sum numbers in a list
  - py_count_vowels     : loop + condition over characters
  - py_sum_digits       : loop over digits of a number
  - py_flatten          : loop + isinstance check
  - py_title_words      : string split + capitalize

Grade 2 (Dictionaries, Set Logic, Classic Interview Problems):
  - py_fizzbuzz, py_is_anagram, py_second_largest, py_chunk, py_gcd, py_dedupe

Grade 3 (Algorithms & Self-Authored Causal Exploration):
  - py_binary_search, py_roman, + self_causal_explore (write own function & predict output)
"""
from viv_reference_examples import REFERENCE

TASKS = [
    # --- GRADE 0: DAY-1 FUNDAMENTALS ---
    {"id": "py0_hello_world", "level": 0,
     "spec": "Write a Python program or function `hello_world()` that prints 'Hello, World!' to stdout and returns 'Hello, World!'",
     "tests": "out = hello_world()\nassert out == 'Hello, World!'",
     "reference": "def hello_world() -> str:\n    msg = 'Hello, World!'\n    print(msg)\n    return msg"},
    {"id": "py0_variable_assign", "level": 0,
     "spec": "def make_greeting() -> str: create a variable `name = 'Viv'` and return the string 'I am Viv'",
     "tests": "assert make_greeting() == 'I am Viv'",
     "reference": "def make_greeting() -> str:\n    name = 'Viv'\n    return 'I am ' + name"},
    {"id": "py0_add_two", "level": 0,
     "spec": "def add_two(a: int, b: int) -> int: return the sum of a and b",
     "tests": "assert add_two(2, 3) == 5\nassert add_two(0, 0) == 0\nassert add_two(-1, 5) == 4",
     "reference": "def add_two(a: int, b: int) -> int:\n    return a + b"},
    {"id": "py0_string_join", "level": 0,
     "spec": "def greet(name: str) -> str: return 'Hello, ' followed by name and an exclamation mark '!'",
     "tests": "assert greet('World') == 'Hello, World!'\nassert greet('Viv') == 'Hello, Viv!'",
     "reference": "def greet(name: str) -> str:\n    return f'Hello, {name}!'"},
    {"id": "py0_string_length", "level": 0,
     "spec": "def string_length(s: str) -> int: return the number of characters in s",
     "tests": "assert string_length('') == 0\nassert string_length('abc') == 3\nassert string_length('hello world') == 11",
     "reference": "def string_length(s: str) -> int:\n    return len(s)"},

    # --- GRADE 1: DECISIONS, LOOPS & LISTS ---
    {"id": "py1_is_even", "level": 1,
     "spec": "def is_even(n: int) -> bool: return True if n is divisible by 2, else False",
     "tests": "assert is_even(0) is True\nassert is_even(4) is True\nassert is_even(7) is False",
     "reference": "def is_even(n: int) -> bool:\n    return n % 2 == 0"},
    {"id": "py1_count_to_n", "level": 1,
     "spec": "def count_to_n(n: int) -> list[int]: return a list of integers from 1 up to n inclusive",
     "tests": "assert count_to_n(3) == [1, 2, 3]\nassert count_to_n(0) == []\nassert count_to_n(1) == [1]",
     "reference": "def count_to_n(n: int) -> list[int]:\n    return list(range(1, n + 1))"},
    {"id": "py1_sum_list", "level": 1,
     "spec": "def sum_list(xs: list[int]) -> int: return the sum of all numbers in xs",
     "tests": "assert sum_list([1, 2, 3]) == 6\nassert sum_list([]) == 0\nassert sum_list([10, -2]) == 8",
     "reference": "def sum_list(xs: list[int]) -> int:\n    total = 0\n    for x in xs:\n        total += x\n    return total"},
    {"id": "py_sum_digits", "level": 1, "spec": "def sum_digits(n: int) -> int: sum of the decimal digits of a non-negative integer",
     "tests": "assert sum_digits(0)==0\nassert sum_digits(123)==6\nassert sum_digits(9999)==36",
     "reference": "def sum_digits(n: int) -> int:\n    return sum(int(d) for d in str(n))"},
    {"id": "py_fizzbuzz", "level": 2, "spec": "def fizzbuzz(n: int) -> list[str]: return a list of strings for 1..n where multiples of 15 are 'FizzBuzz', multiples of 3 are 'Fizz', multiples of 5 are 'Buzz', else str(i). Example for n=5: ['1', '2', 'Fizz', '4', 'Buzz']. Use standard library loop, do not import numpy. Return list[str].",
     "tests": "assert fizzbuzz(5)==['1','2','Fizz','4','Buzz']\nassert fizzbuzz(15)[-1]=='FizzBuzz'\nassert fizzbuzz(0)==[]",
     "reference": "def fizzbuzz(n: int) -> list[str]:\n    out = []\n    for i in range(1, n + 1):\n        if i % 15 == 0:\n            out.append('FizzBuzz')\n        elif i % 3 == 0:\n            out.append('Fizz')\n        elif i % 5 == 0:\n            out.append('Buzz')\n        else:\n            out.append(str(i))\n    return out"},
    {"id": "py_flatten", "level": 1, "spec": "def flatten(xs: list) -> list: flatten one level of nesting; non-list items stay as they are",
     "tests": "assert flatten([[1,2],[3],[]])==[1,2,3]\nassert flatten([1,[2,3],4])==[1,2,3,4]\nassert flatten([])==[]",
     "reference": "def flatten(xs: list) -> list:\n    out = []\n    for x in xs:\n        if isinstance(x, list):\n            out.extend(x)\n        else:\n            out.append(x)\n    return out"},
    {"id": "py_is_anagram", "level": 2, "spec": "def is_anagram(a: str, b: str) -> bool: same letters ignoring case and spaces",
     "tests": "assert is_anagram('Listen','Silent')\nassert is_anagram('a gentleman','elegant man')\nassert not is_anagram('abc','abd')\nassert is_anagram('','')",
     "reference": "def is_anagram(a: str, b: str) -> bool:\n    clean = lambda s: sorted(c.lower() for c in s if not c.isspace())\n    return clean(a) == clean(b)"},
    {"id": "py_second_largest", "level": 2, "spec": "def second_largest(xs: list[int]) -> int | None: Return the second largest distinct number by sorting the deduplicated set: s = sorted(set(xs)). If len(s) < 2 return None, else return s[-2]. Standard library only.",
     "tests": "assert second_largest([1,2,3])==2\nassert second_largest([5,5,5]) is None\nassert second_largest([2,2,1])==1\nassert second_largest([]) is None",
     "reference": "def second_largest(xs: list[int]):\n    d = sorted(set(xs), reverse=True)\n    return d[1] if len(d) > 1 else None"},
    {"id": "py_chunk", "level": 2, "spec": "def chunk(xs: list, n: int) -> list[list]: split xs into consecutive pieces of length n using slicing (standard library only, do not import numpy); last piece may be shorter",
     "tests": "assert chunk([1,2,3,4,5],2)==[[1,2],[3,4],[5]]\nassert chunk([],3)==[]\nassert chunk([1,2,3],3)==[[1,2,3]]",
     "reference": "def chunk(xs: list, n: int) -> list[list]:\n    return [xs[i:i + n] for i in range(0, len(xs), n)]"},
    {"id": "py_count_vowels", "level": 1, "spec": "def count_vowels(s: str) -> int: count of a, e, i, o, u in any case",
     "tests": "assert count_vowels('Hello')==2\nassert count_vowels('xyz')==0\nassert count_vowels('AEIOU')==5\nassert count_vowels('')==0",
     "reference": "def count_vowels(s: str) -> int:\n    return sum(1 for c in s.lower() if c in 'aeiou')"},
    {"id": "py_title_words", "level": 1, "spec": "def title_words(s: str) -> str: capitalize the first letter of each space-separated word and lowercase the rest, keeping single spaces",
     "tests": "assert title_words('hello wORLD')=='Hello World'\nassert title_words('a')=='A'\nassert title_words('')==''",
     "reference": "def title_words(s: str) -> str:\n    return ' '.join(w[:1].upper() + w[1:].lower() for w in s.split(' '))"},
    {"id": "py_gcd", "level": 2, "spec": "def gcd(a: int, b: int) -> int: greatest common divisor of two non-negative integers, gcd(a,0)=a",
     "tests": "assert gcd(12,18)==6\nassert gcd(7,0)==7\nassert gcd(17,5)==1\nassert gcd(0,0)==0",
     "reference": "def gcd(a: int, b: int) -> int:\n    while b:\n        a, b = b, a % b\n    return a"},
    {"id": "py_binary_search", "level": 3, "spec": "def binary_search(xs: list[int], target: int) -> int: index of target in the sorted list, or -1",
     "tests": "assert binary_search([1,3,5,7],5)==2\nassert binary_search([1,3,5,7],4)==-1\nassert binary_search([],1)==-1\nassert binary_search([2],2)==0",
     "reference": "def binary_search(xs: list[int], target: int) -> int:\n    lo, hi = 0, len(xs) - 1\n    while lo <= hi:\n        mid = (lo + hi) // 2\n        if xs[mid] == target:\n            return mid\n        if xs[mid] < target:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return -1"},
    {"id": "py_roman", "level": 3, "spec": "def to_roman(n: int) -> str: return Roman numeral string. Use dictionary mapping d = {1000:'M', 900:'CM', 500:'D', 400:'CD', 100:'C', 90:'XC', 50:'L', 40:'XL', 10:'X', 9:'IX', 5:'V', 4:'IV', 1:'I'}. out = ''. For val, sym in d.items(): while n >= val: out += sym; n -= val. Return out.",
     "tests": "assert to_roman(4)=='IV'\nassert to_roman(9)=='IX'\nassert to_roman(1994)=='MCMXCIV'\nassert to_roman(3999)=='MMMCMXCIX'",
     "reference": "def to_roman(n: int) -> str:\n    d = {1000:'M', 900:'CM', 500:'D', 400:'CD', 100:'C', 90:'XC', 50:'L', 40:'XL', 10:'X', 9:'IX', 5:'V', 4:'IV', 1:'I'}\n    out = ''\n    for val, sym in d.items():\n        while n >= val:\n            out += sym\n            n -= val\n    return out"},
    {"id": "py_dedupe", "level": 2, "spec": "def dedupe(xs: list) -> list: remove duplicates, keep first occurrence order",
     "tests": "assert dedupe([3,1,3,2,1])==[3,1,2]\nassert dedupe([])==[]\nassert dedupe(['a','a'])==['a']",
     "reference": "def dedupe(xs: list) -> list:\n    seen = set()\n    out = []\n    for x in xs:\n        if x not in seen:\n            seen.add(x)\n            out.append(x)\n    return out"},
]

for _t in TASKS:
    _t["lang"] = "python"
    REFERENCE[_t["id"]] = _t["reference"]
