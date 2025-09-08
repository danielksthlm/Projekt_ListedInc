import sys
import argparse
import pathlib

# Lägg bootstrap-projektet på sys.path
sys.path.insert(0, "/Users/danielkallberg/Documents/KLR_AI/Bootstrap/klrab_bootstrap_project")

from klrab_bootstrap.doctor import run_doctor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(pathlib.Path().resolve()))
    args = ap.parse_args()
    rv = run_doctor(args.root)
    if rv is not None:
        print(rv)


if __name__ == "__main__":
    main()
