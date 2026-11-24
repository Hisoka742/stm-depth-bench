"""Типы значений слотов: допустимые диапазоны, согласованные изменения и разбор ответов.

Для каждого типа заданы:
  sample(rng)                 — случайное значение из допустимого диапазона;
  key(v) / from_key(x)        — числовой ключ для упорядоченных типов (дата, сумма, время);
  near(rng, v)                — близкие значения для исправления ошибки (перепутанные цифры,
                                соседний номер дома, соседний день и т. п.);
  canon(v)                    — каноническая форма для сравнения;
  extract(text)               — все значения этого типа в свободном тексте ответа, в канонической
                                форме и в порядке появления (сравнение с эталоном выполняет код).

Причина изменения задаёт ограничение на новое значение (п. 2.1.2 ВКР): направление
(«up» — больше / позже, «down» — меньше / раньше, «any») и, для времени, допустимые
интервалы для прежнего и нового значения.
"""
from __future__ import annotations

import random
import re

# ---------------------------------------------------------------- общие функции


def _norm(text: str) -> str:
    return text.lower().replace("ё", "е").replace(" ", " ")


def _swap_adjacent(s: str) -> list[str]:
    out = []
    for i in range(len(s) - 1):
        if s[i] != s[i + 1]:
            out.append(s[:i] + s[i + 1] + s[i] + s[i + 2:])
    return out


def _uniq(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


# ---------------------------------------------------------------- адрес
STREETS = ["Садовая", "Лесная", "Школьная", "Заводская", "Полевая", "Речная", "Солнечная",
           "Парковая", "Луговая", "Береговая", "Вишневая", "Зеленая", "Цветочная", "Песочная",
           "Морская", "Северная", "Спортивная", "Сосновая", "Липовая", "Рябиновая", "Кленовая",
           "Майская", "Светлая", "Почтовая", "Торговая", "Дачная", "Набережная", "Каштановая"]
STEMS = [s[:-2].lower() for s in STREETS]
assert len(set(STEMS)) == len(STEMS)
_ADDR_RX = re.compile(r"(?<![а-я])(" + "|".join(STEMS) + r")[а-я]*[^\d\n]{0,25}?(?<!\d)(\d{1,3})(?!\d)")


class Addr:
    vtype = "addr"
    ordered = False
    regex = r"ул\. [А-ЯЁ][а-яё]+, \d+"

    @staticmethod
    def sample(rng):
        return f"ул. {rng.choice(STREETS)}, {rng.randint(1, 60)}"

    @staticmethod
    def canon(v):
        r = Addr.extract(v)
        return r[0] if r else None

    @staticmethod
    def near(rng, v):
        street, num = re.match(r"ул\. (\S+), (\d+)", v).groups()
        n = int(num)
        nums = [n + 1, n - 1, n + 2, n - 2] + [int(x) for x in _swap_adjacent(num) if x[0] != "0"]
        return [f"ул. {street}, {x}" for x in _uniq(nums) if 1 <= x <= 99 and x != n]

    @staticmethod
    def extract(text):
        return _uniq((m.group(1), int(m.group(2))) for m in _ADDR_RX.finditer(_norm(text)))


# ---------------------------------------------------------------- дата (декабрь — январь)
MONTHS = [("декабря", 12, 31), ("января", 1, 31)]
_MON_RX = {"декабр": 12, "дек": 12, "январ": 1, "янв": 1}
_DATE_W = re.compile(r"(?<!\d)(\d{1,2})(?:-?(?:го|е|ое))?\s+(декабр|январ|дек|янв)")
_DATE_N = re.compile(r"(?<![\d.:])(\d{1,2})[./](\d{1,2})(?:[./]\d{2,4})?(?![\d:])")


class Date:
    vtype = "date"
    ordered = True
    regex = r"(?<!\d)\d{1,2} (?:декабря|января)"
    lo, hi = 1, 62               # 1 декабря .. 31 января
    min_step = 2

    @staticmethod
    def max_step(x, direction):
        return 21                # перенос не больше чем на три недели

    @staticmethod
    def from_key(x):
        return f"{x} декабря" if x <= 31 else f"{x - 31} января"

    @staticmethod
    def key(v):
        d, m = v.split()
        return int(d) + (0 if m == "декабря" else 31)

    @staticmethod
    def sample(rng):
        return Date.from_key(rng.randint(Date.lo, Date.hi))

    @staticmethod
    def canon(v):
        d, m = v.split()
        return (int(d), 12 if m == "декабря" else 1)

    @staticmethod
    def near(rng, v):
        x = Date.key(v)
        d = int(v.split()[0])
        cands = [x + 1, x - 1, x + 2, x - 2]
        for s in _swap_adjacent(str(d)):
            if s[0] != "0" and 1 <= int(s) <= 31:
                cands.append(x - d + int(s))
        return [Date.from_key(c) for c in _uniq(cands) if Date.lo <= c <= Date.hi and c != x]

    @staticmethod
    def extract(text):
        t = _norm(text)
        found = []
        for m in _DATE_W.finditer(t):
            found.append((m.start(), (int(m.group(1)), _MON_RX[m.group(2)])))
        for m in _DATE_N.finditer(t):
            d, mo = int(m.group(1)), int(m.group(2))
            if mo in (12, 1) and 1 <= d <= 31:
                found.append((m.start(), (d, mo)))
        return _uniq(v for _, v in sorted(found))


# ---------------------------------------------------------------- сумма (тысячи рублей)
_MONEY_RX = re.compile(r"(?<![\d+])(\d{1,3}(?: \d{3})+|\d+)(?:[.,](\d+))?\s*(тыс[а-я]*\.?|к(?![а-я])|млн[а-я]*)?")


class Money:
    vtype = "money"
    ordered = True
    regex = r"\d{1,3} 000 рублей"
    lo, hi = 10, 300             # тысяч рублей
    min_step = 5

    @staticmethod
    def max_step(x, direction):
        return max(15, x) if direction == "up" else max(10, x // 2)   # не больше чем вдвое

    @staticmethod
    def from_key(x):
        return f"{x} 000 рублей"

    @staticmethod
    def key(v):
        return int(v.split()[0])

    @staticmethod
    def sample(rng):
        return Money.from_key(rng.randrange(Money.lo, Money.hi + 1, 5))

    @staticmethod
    def canon(v):
        return Money.key(v) * 1000

    @staticmethod
    def near(rng, v):
        x = Money.key(v)
        s = str(x)
        cands = [int(t) for t in _swap_adjacent(s) if t[0] != "0"]
        for i, ch in enumerate(s):
            for dd in (1, -1):
                nd = int(ch) + dd
                if 0 <= nd <= 9 and not (i == 0 and nd == 0):
                    cands.append(int(s[:i] + str(nd) + s[i + 1:]))
        return [Money.from_key(c) for c in _uniq(cands) if Money.lo <= c <= Money.hi and c != x]

    @staticmethod
    def extract(text):
        t = _norm(text)
        out = []
        for m in _MONEY_RX.finditer(t):
            num = int(m.group(1).replace(" ", ""))
            unit = m.group(3) or ""
            frac = m.group(2)
            if unit.startswith("тыс") or unit == "к":
                val = num * 1000 + (int(frac.ljust(3, "0")[:3]) if frac else 0)
            elif unit.startswith("млн"):
                val = num * 1_000_000 + (int(frac.ljust(6, "0")[:6]) if frac else 0)
            elif num >= 1000 and not frac:
                val = num
            else:
                continue
            out.append(val)
        return _uniq(out)


# ---------------------------------------------------------------- телефон
_PHONE_RX = re.compile(r"(?:\+\s*7|(?<!\d)8)?[\s(.-]*\d{3}[\s).-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)")


class Phone:
    vtype = "phone"
    ordered = False
    regex = r"\+7 9\d{2} \d{3}-\d{2}-\d{2}"

    @staticmethod
    def fmt(d10):
        return f"+7 {d10[:3]} {d10[3:6]}-{d10[6:8]}-{d10[8:]}"

    @staticmethod
    def sample(rng):
        return Phone.fmt(f"9{rng.randint(0, 99):02d}{rng.randint(100, 999)}{rng.randint(10, 99)}{rng.randint(10, 99)}")

    @staticmethod
    def canon(v):
        return re.sub(r"\D", "", v)[-10:]

    @staticmethod
    def near(rng, v):
        d = Phone.canon(v)
        cands = [d[:3] + t for t in _swap_adjacent(d[3:])]
        return [Phone.fmt(c) for c in _uniq(cands) if c != d]

    @staticmethod
    def extract(text):
        out = []
        for m in _PHONE_RX.finditer(text):
            digits = re.sub(r"\D", "", m.group(0))
            if len(digits) >= 10:
                out.append(digits[-10:])
        return _uniq(out)


# ---------------------------------------------------------------- время (часы работы банка)
_TIME_HM = re.compile(r"(?<![\d.:])(\d{1,2})[:.](\d{2})(?![\d])")
_TIME_H = re.compile(r"(?<![\d.:])(\d{1,2})(?:\s*(?:час[а-я]*|ч\.?))?(?:\s*(\d{1,2})\s*мин[а-я]*)?\s+(утра|дня|вечера)?")


class Time:
    vtype = "time"
    ordered = True
    regex = r"(?<![\d:])\d{1,2}:\d{2}(?![\d:])"
    lo, hi = 9 * 60, 20 * 60     # звонки — с 9:00 до 20:00
    step = 30
    min_step = 60

    @staticmethod
    def max_step(x, direction):
        return 24 * 60

    @staticmethod
    def from_key(x):
        return f"{x // 60}:{x % 60:02d}"

    @staticmethod
    def key(v):
        h, m = v.split(":")
        return int(h) * 60 + int(m)

    @staticmethod
    def sample(rng):
        return Time.from_key(rng.randrange(Time.lo, Time.hi + 1, Time.step))

    @staticmethod
    def canon(v):
        return Time.key(v)

    @staticmethod
    def near(rng, v):
        x = Time.key(v)
        cands = [x + 60, x - 60, x + 30, x - 30]
        return [Time.from_key(c) for c in _uniq(cands) if Time.lo <= c <= Time.hi and c != x]

    @staticmethod
    def extract(text):
        t = _norm(text)
        found, spans = [], []
        sfx = r"(?:\s*(утра|дня|вечера))?"
        pats = [r"(?<![\d.:])(\d{1,2})[:.](\d{2})(?!\d)" + sfx,                       # 7:30, 07.30 вечера
                r"(?<![\d.:])(\d{1,2})\s*ч(?:ас[а-я]*)?\.?(?:\s*(\d{1,2})\s*мин[а-я]*)?" + sfx,  # 18 ч 30 мин
                r"(?<![\d.:])(\d{1,2})()\s+(утра|дня|вечера)"]                           # 9 утра
        for rx in pats:
            for m in re.finditer(rx, t):
                if any(a < m.end() and m.start() < b for a, b in spans):
                    continue
                h, mi = int(m.group(1)), int(m.group(2) or 0)
                if m.group(3) in ("дня", "вечера") and h < 12:
                    h += 12
                if h <= 23 and mi < 60:
                    found.append((m.start(), h * 60 + mi))
                    spans.append((m.start(), m.end()))
        return _uniq(v for _, v in sorted(found))


# ---------------------------------------------------------------- карта (последние четыре цифры)
_CARD_RX = re.compile(r"(?<![\d:.,])(\d{4})(?![\d:.,]\d|\d)")


class Card:
    vtype = "card"
    ordered = False
    regex = r"\*\d{4}"

    @staticmethod
    def sample(rng):
        return f"*{rng.randint(1000, 9999)}"

    @staticmethod
    def canon(v):
        return v[-4:]

    @staticmethod
    def near(rng, v):
        d = v[-4:]
        return [f"*{t}" for t in _swap_adjacent(d) if t[0] != "0" and t != d]

    @staticmethod
    def extract(text):
        return _uniq(m.group(1) for m in _CARD_RX.finditer(text))


TYPES = {c.vtype: c for c in (Addr, Date, Money, Phone, Time, Card)}


def error_kind(old: str, new: str) -> str:
    """Вид ошибки, которую исправляет клиент: перестановка соседних цифр («swap»), одна неверная
    цифра («digit») или соседнее значение — другой день, час, номер дома («adjacent»)."""
    a, b = re.sub(r"\D", "", old), re.sub(r"\D", "", new)
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]:
            return "swap"
        if len(diff) == 1:
            return "digit"
    return "adjacent"


# ---------------------------------------------------------------- согласование с причиной
def satisfies(vt, old: str | None, new: str, cons: dict | None, busy: list | None = None) -> bool:
    """Удовлетворяет ли новое значение ограничению причины.

    cons: dir — направление («up», «down»); busy — интервал, занятый по этой причине (для времени:
    прежнее значение в нём лежит, новое — нет). busy (аргумент) — все интервалы, занятые по
    причинам, названным раньше в той же цепочке: новое значение не должно в них попадать.
    """
    if not vt.ordered:
        return True
    b = vt.key(new)
    for a0, a1 in (busy or []):
        if a0 <= b < a1:
            return False
    if not cons or old is None:
        return True
    a = vt.key(old)
    if cons.get("busy"):
        lo, hi = cons["busy"]
        if lo <= b < hi:
            return False
        if not (lo <= a < hi):
            return False
        if abs(b - a) < vt.min_step:
            return False
    d = cons.get("dir", "any")
    if d == "up":
        return vt.min_step <= b - a <= vt.max_step(a, "up")
    if d == "down":
        return vt.min_step <= a - b <= vt.max_step(a, "down")
    return True


def applicable(vt, old: str, cons: dict | None, prev_cons: dict | None = None, resolves: dict | None = None) -> bool:
    """Подходит ли причина к текущему значению и к предыдущей причине.

    Для времени прежнее значение должно лежать в интервале, который причина делает занятым.
    Если причина меняет направление по сравнению с предыдущей причиной, она должна снимать
    предыдущую (resolves: группа предыдущей причины -> группы, которые её снимают).
    """
    if not cons or not vt.ordered:
        return True
    if cons.get("busy"):
        lo, hi = cons["busy"]
        if not (lo <= vt.key(old) < hi):
            return False
    if prev_cons and resolves is not None and prev_cons.get("dir") and cons.get("dir")             and prev_cons["dir"] != cons["dir"]:
        if cons.get("g") not in resolves.get(prev_cons.get("g"), ()):
            return False
    return True


def step_values(vt, rng: random.Random, old: str, cons: dict | None, used: set, busy: list | None = None) -> list[str]:
    """Все допустимые новые значения после причины с ограничением cons."""
    if not vt.ordered:
        out = []
        for _ in range(200):
            v = vt.sample(rng)
            if vt.canon(v) not in used and v != old:
                out.append(v)
            if len(out) >= 20:
                break
        return out
    stepk = getattr(vt, "step", 1)
    if vt is Money:
        stepk = 5
    keys = range(vt.lo, vt.hi + 1, stepk) if vt is not Date else range(vt.lo, vt.hi + 1)
    return [vt.from_key(k) for k in keys
            if vt.canon(vt.from_key(k)) not in used and satisfies(vt, old, vt.from_key(k), cons, busy)]
