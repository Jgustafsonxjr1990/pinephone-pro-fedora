"""Strict LF-framed machine receipts; current buffer ends are never receipts."""
import re


class CompleteLines:
    def __init__(self, limit=4096):
        self.limit = limit
        self.pending = bytearray()
        self.discarding = False

    def feed(self, chunk):
        lines = []
        for byte in chunk:
            if byte == 10:
                if not self.discarding:
                    line = bytes(self.pending)
                    if line.endswith(b"\r"):
                        line = line[:-1]
                    lines.append(line)
                self.pending.clear()
                self.discarding = False
            elif not self.discarding:
                self.pending.append(byte)
                if len(self.pending) > self.limit:
                    self.pending.clear()
                    self.discarding = True
        return lines


def receipt_pattern(command_id, token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", command_id):
        raise ValueError("Invalid command ID")
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ValueError("Invalid command token")
    return re.compile(rb"PPP_CMD_DONE_" + re.escape(command_id.encode("ascii"))
                      + rb" TOKEN=" + token.encode("ascii")
                      + rb" EXIT=(0|[1-9][0-9]{0,2})")


def parse_receipt(line, pattern):
    match = pattern.fullmatch(line)
    if match is None:
        return None
    status = int(match.group(1))
    return status if status <= 255 else None
