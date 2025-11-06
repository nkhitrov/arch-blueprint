from arch_blueprint.blueprint import ArchBlueprint
import argparse


def main():
    parser = argparse.ArgumentParser(
        description="Generate component diagrams in plantuml for python applications"
    )
    parser.add_argument(
        "root", type=str, help="Name of root python module in project (example: 'myapp'"
    )
    parser.add_argument(
        "--modules",
        "-m",
        type=str,
        nargs="*",
        action="extend",
        help="Selected modules for rendering (examples: 'myapp.somemodule', 'myapp.somemodule.*', 'myapp.somemodule.**')",
    )
    args = parser.parse_args()

    ArchBlueprint(root=args.root, target_names=args.modules).run()


main()
