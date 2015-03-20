import re

try:
    import colorama
except ImportError:
    colorama = Tokens = Reset = None
else:
    from colorama import Fore, Back, Style
    colorama.init()

    Tokens = {
        'b': Fore.BLUE,
        'c': Fore.CYAN,
        'g': Fore.GREEN,
        'm': Fore.MAGENTA,
        'r': Fore.RED,
        'y': Fore.YELLOW,
    }
    Reset = Style.RESET_ALL

TokenPattern = re.compile(r'\[!([bcgmryBCGMRY])?\]')

def _replace_tokens(match):
    token = match.group(1)
    if not token:
        return Style.RESET_ALL

    replacement = Tokens[token.lower()]
    if token.isupper():
        return replacement + Style.BRIGHT
    else:
        return replacement

def ansify(value, colorize=False, reset=True):
    if colorama and colorize:
        value = TokenPattern.sub(_replace_tokens, value)
        if reset:
            value += Reset
        return value
    else:
        return TokenPattern.sub('', value)
