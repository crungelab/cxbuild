import subprocess


class Tool:
    def __init__(self) -> None:
        pass

    def run(self, command: list):
        #subprocess.check_call(command)
        subprocess.run(command)
