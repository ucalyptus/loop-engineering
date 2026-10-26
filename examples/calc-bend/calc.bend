import Base

# Three arithmetic functions on Nat, each with one planted bug.
# The spec is in laws_*.bend; the loop is done when every law is proven.

def add(a: Nat, b: Nat) -> Nat:
  match b:
    case 0n:
      a
    case 1n+p:
      add(a, p)

def mul(+a: Nat, b: Nat) -> Nat:
  match b:
    case 0n:
      a
    case 1n+p:
      add(mul(a, p), a)

def double(n: Nat) -> Nat:
  match n:
    case 0n:
      0n
    case 1n+p:
      1n+double(p)
