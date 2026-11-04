"""Independent arithmetic Jalali/Gregorian date utilities (range aimed at 1300-1499 SH).
All persistent dates are ISO Gregorian. No dependence on operating-system locale.
"""
from datetime import date


def _ascii_digits(value):
    return str(value).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'))


def gregorian_to_jalali(day):
    gy, gm, gd = day.year, day.month, day.day
    offsets = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + offsets[gm-1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def jalali_to_gregorian(year, month, day):
    jy, jm, jd = int(year) + 1595, int(month), int(day)
    if not (1300 <= int(year) <= 1499 and 1 <= jm <= 12 and 1 <= jd <= 31):
        raise ValueError('تاریخ شمسی خارج از محدوده است.')
    days = -355668 + 365*jy + (jy//33)*8 + ((jy % 33)+3)//4 + jd
    days += (jm-1)*31 if jm < 7 else 186 + (jm-7)*30
    gy = 400 * (days//146097)
    days %= 146097
    if days > 36524:
        gy += 100 * ((days-1)//36524)
        days = (days-1) % 36524
        if days >= 365:
            days += 1
    gy += 4*(days//1461)
    days %= 1461
    if days > 365:
        gy += (days-1)//365
        days = (days-1)%365
    gd = days + 1
    leap = gy%4 == 0 and (gy%100 != 0 or gy%400 == 0)
    lengths = (31,29 if leap else 28,31,30,31,30,31,31,30,31,30,31)
    gm = 1
    for duration in lengths:
        if gd <= duration:
            break
        gd -= duration
        gm += 1
    result = date(gy, gm, gd)
    if gregorian_to_jalali(result) != (int(year), jm, jd):
        raise ValueError('روز ماه در تقویم شمسی معتبر نیست.')
    return result


def parse_jalali(text):
    text = _ascii_digits(text).strip().replace('/', '-')
    parts = text.split('-')
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError('تاریخ را به‌شکل ۱۴۰۵/۰۸/۰۵ وارد کنید.')
    return jalali_to_gregorian(*(int(x) for x in parts))


def display_jalali(value):
    if isinstance(value, str):
        value = date.fromisoformat(value)
    y, m, d = gregorian_to_jalali(value)
    return '{:04d}/{:02d}/{:02d}'.format(y, m, d)


def rial_number(text):
    raw = _ascii_digits(text).replace(',', '').replace('٬', '').replace(' ', '').strip()
    if not raw or not raw.isdigit():
        raise ValueError('مبلغ باید یک عدد صحیح ریالی و غیرمنفی باشد.')
    amount = int(raw)
    if amount > 9_000_000_000_000_000:
        raise ValueError('مبلغ بیش از حد مجاز است.')
    return amount


def fmt_rial(number):
    return '{:,}'.format(number)
