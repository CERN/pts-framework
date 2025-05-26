from pathlib import Path

"""Module that provides the utilities to the project.
    """

def get_project_root() -> Path:
    return Path(__file__).parent.parent.parent

if __name__ == "__main__":
    print(get_project_root())

