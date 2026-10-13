"""python -m pytest workflow/figma-frames/scripts  (or: python test_figma.py)"""
from figma import describe, hex_color, parse_target


def test_parse_target():
    assert parse_target("https://www.figma.com/design/TG8BfmF3vc19sZOUFeL14s/Vital-CRM?node-id=11538-113252&p=f") == ("TG8BfmF3vc19sZOUFeL14s", "11538:113252")
    assert parse_target("https://www.figma.com/file/abcDEF123/x") == ("abcDEF123", None)
    assert parse_target("abcDEF123") == ("abcDEF123", None)


def test_hex_color():
    assert hex_color({"r": 0.0549, "g": 0.5255, "b": 0.9961, "a": 1}) == "#0e86fe"
    assert hex_color({"r": 0.1373, "g": 0.1373, "b": 0.1961, "a": 1}, 0.85) == "#232332@0.85"


def test_describe_text():
    n = {"type": "TEXT", "name": "Label", "characters": "解除連結",
         "style": {"fontSize": 14, "fontWeight": 500, "lineHeightPx": 20},
         "fills": [{"type": "SOLID", "color": {"r": 0.1373, "g": 0.1373, "b": 0.1961, "a": 1}, "opacity": 0.55}]}
    assert describe(n) == 'TEXT "Label" "解除連結" font=14/500/lh20 color=#232332@0.55'


if __name__ == "__main__":
    test_parse_target()
    test_hex_color()
    test_describe_text()
    print("ok")
