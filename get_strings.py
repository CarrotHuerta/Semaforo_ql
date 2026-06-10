import ast

def get_strings(filename):
    with open(filename, 'r') as f:
        tree = ast.parse(f.read())

    strings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if len(node.value) > 2 and not node.value.startswith("#") and not node.value.startswith("QFrame"):
                strings.add(node.value)

    for s in sorted(strings):
        print(f'    "{s}": "",')

if __name__ == "__main__":
    get_strings("main.py")
