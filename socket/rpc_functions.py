# rpc_functions.py
import math


def floor_func(x: float) -> int:
    """10進数 x を最も近い整数に切り捨てる (math.floor)"""
    return math.floor(x)


def nroot(n: int, x: int) -> float:
    """
    n 次根を計算する。
    r^n = x となる r を返す。r = x^(1/n)
    """
    if n == 0:
        raise ValueError("n must not be zero.")
    return x ** (1.0 / n)


def reverse_str(s: str) -> str:
    """文字列 s を逆にした新しい文字列を返す"""
    return s[::-1]


def valid_anagram(str1: str, str2: str) -> bool:
    """
    2つの文字列 str1, str2 がアナグラムか判定
    (文字の出現回数が同じであるかどうか)
    """
    return sorted(str1) == sorted(str2)


def sort_strings(str_arr: list[str]) -> list[str]:
    """文字列配列をソートして返す"""
    return sorted(str_arr)
