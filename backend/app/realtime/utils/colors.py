class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    GRAY = '\033[90m'
    RESET = '\033[0m'

    @staticmethod
    def apply(text):
        class Wrapper:
            def __init__(self, text):
                self.text = text
            def red(self): return f"{Colors.RED}{self.text}{Colors.RESET}"
            def green(self): return f"{Colors.GREEN}{self.text}{Colors.RESET}"
            def yellow(self): return f"{Colors.YELLOW}{self.text}{Colors.RESET}"
            def blue(self): return f"{Colors.BLUE}{self.text}{Colors.RESET}"
            def magenta(self): return f"{Colors.MAGENTA}{self.text}{Colors.RESET}"
            def cyan(self): return f"{Colors.CYAN}{self.text}{Colors.RESET}"
            def white(self): return f"{Colors.WHITE}{self.text}{Colors.RESET}"
            def gray(self): return f"{Colors.GRAY}{self.text}{Colors.RESET}"
        return Wrapper(text)
