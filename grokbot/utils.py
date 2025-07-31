import asyncio
from collections import deque
import aiofiles
import json
import time

async def tail(filename, n):
    loop = asyncio.get_running_loop()
    def read_tail():
        try:
            with open(filename, 'r') as f:
                return list(deque(f, n))
        except FileNotFoundError:
            return ["Log file not found."]
        except Exception as e:
            return [f"Error reading log file: {str(e)}"]
    return await loop.run_in_executor(None, read_tail)

def split_log_lines(lines, max_length):
    chunks = []
    current_chunk = []
    current_length = 0
    for line in lines:
        line_length = len(line)
        if current_length + line_length > max_length:
            if current_chunk:
                chunks.append(''.join(current_chunk))
                current_chunk = []
                current_length = 0
        current_chunk.append(line)
        current_length += line_length
    if current_chunk:
        chunks.append(''.join(current_chunk))
    return chunks

def split_message(text, max_length):
    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        split_point = max_length
        search_range = max(0, max_length - 100)
        for i in range(min(max_length, len(text)), search_range, -1):
            if text[i - 1] in "\n.!?":
                split_point = i
                break
        else:
            for i in range(min(max_length, len(text)), search_range, -1):
                if text[i - 1] == " ":
                    split_point = i
                    break
        chunks.append(text[:split_point].rstrip())
        text = text[split_point:].lstrip()
    return [chunk for chunk in chunks if chunk]