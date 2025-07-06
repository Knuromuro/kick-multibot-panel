import argparse
from shared.kick import login


def main() -> None:
    parser = argparse.ArgumentParser(description="Login to Kick and print auth_token")
    parser.add_argument("--email", required=True, help="Kick account email")
    parser.add_argument("--password", required=True, help="Kick account password")
    args = parser.parse_args()
    token = login(args.email, args.password)
    print(token)


if __name__ == "__main__":
    main()
