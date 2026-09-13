"""Расшифровка ссылок VK Music (audio_api_unavailable.mp3?extra=…).

Алгоритм из vk_api (Apache 2.0, python273).
"""

from __future__ import annotations

VK_STR = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMN0PQRSTUVWXYZO123456789+/="


class VkAudioUrlDecodeError(ValueError):
    pass


def _splice(items: list, a: int, b: int, c) -> tuple[list, list]:
    return items[:a] + [c] + items[a + b:], items[a:a + b]


def decode_audio_url(string: str, user_id: int) -> str:
    if "?extra=" not in string:
        raise VkAudioUrlDecodeError("URL без параметра extra")
    vals = string.split("?extra=", 1)[1].split("#")
    tstr = _vk_o(vals[0])
    ops_list = _vk_o(vals[1]).split("\x09")[::-1]
    for op_data in ops_list:
        split_op_data = op_data.split("\x0b")
        cmd = split_op_data[0]
        arg = split_op_data[1] if len(split_op_data) > 1 else None
        if cmd == "v":
            tstr = tstr[::-1]
        elif cmd == "r":
            tstr = _vk_r(tstr, arg)
        elif cmd == "x":
            tstr = _vk_xor(tstr, arg)
        elif cmd == "s":
            tstr = _vk_s(tstr, arg)
        elif cmd == "i":
            tstr = _vk_i(tstr, arg, user_id)
        else:
            raise VkAudioUrlDecodeError(f'Unknown decode cmd: "{cmd}"')
    return tstr


def _vk_o(string: str) -> str:
    result: list[str] = []
    index2 = 0
    i = 0
    for s in string:
        sym_index = VK_STR.find(s)
        if sym_index != -1:
            if index2 % 4 != 0:
                index2 += 1
                i = (i << 6) + sym_index
                result.append(chr(0xFF & i >> (-2 * index2 & 6)))
            else:
                i = sym_index
                index2 += 1
    return "".join(result)


def _vk_r(string: str, shift: str) -> str:
    vk_str2 = VK_STR + VK_STR
    vk_str2_len = len(vk_str2)
    result: list[str] = []
    for s in string:
        index = vk_str2.find(s)
        if index != -1:
            offset = index - int(shift)
            if offset < 0:
                offset += vk_str2_len
            result.append(vk_str2[offset])
        else:
            result.append(s)
    return "".join(result)


def _vk_xor(string: str, key: str) -> str:
    xor_val = ord(key[0])
    return "".join(chr(ord(s) ^ xor_val) for s in string)


def _vk_s_child(text: str, seed: str) -> list[int]:
    length = len(text)
    if not length:
        return []
    order: list[int] = []
    e = int(seed)
    for a in range(length - 1, -1, -1):
        e = (length * (a + 1) ^ e + a) % length
        order.append(e)
    return order[::-1]


def _vk_s(text: str, seed: str) -> str:
    length = len(text)
    if not length:
        return text
    order = _vk_s_child(text, seed)
    chars = list(text)
    for a in range(1, length):
        chars, removed = _splice(chars, order[length - 1 - a], 1, chars[a])
        chars[a] = removed[0]
    return "".join(chars)


def _vk_i(text: str, seed: str, user_id: int) -> str:
    return _vk_s(text, int(seed) ^ user_id)
