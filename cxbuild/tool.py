import subprocess


class Tool:
    def __init__(self) -> None:
        pass

    def run(self, cmd: list):
        #subprocess.check_call(cmd)
        subprocess.run(cmd)
        """
        #cwd = self.config.source_dir
        #env = self.config.env
        try:
            #result = subprocess.run(cmd, cwd=cwd, env=env, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            result = subprocess.run(cmd)
            print("Command executed successfully. Output:\n", result.stdout)
        except subprocess.CalledProcessError as e:
            print(f"Command execution failed with error code {e.returncode}. Error message:\n", e.stderr)
        """