from pathlib import Path

from .solution import Solution

import socket
from loguru import logger

HOST, PORT = 'localhost', 5005

sock = socket.socket(socket.AF_INET, # Internet
                     socket.SOCK_DGRAM) # UDP

def logudp(message: str):
    sock.sendto(bytes(message, 'utf-8'), (HOST, PORT))

logger.add(logudp)

class CxBuild:
    def __init__(self) -> None:
        self.solution = Solution(Path.cwd())

    def configure(self):
        print('configure')
        self.solution.configure()

    def develop(self):
        print('develop')
        self.configure()
        self.solution.develop()

    def build(self):
        print('build')
        self.configure()
        self.solution.build()

    def install(self):
        print('install')
        self.solution.install()
