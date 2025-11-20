def run_shell():
    print("Welcome to the shell. Type 'help' for commands, 'exit' to quit.")
    while True:
        cmd = input(">> ").strip()
        if cmd in ("exit", "quit"):
            print("Exiting.")
            break
        elif cmd == "help":
            print("Commands:\n- help\n- exit\n- your custom commands")
        elif cmd.startswith("do"):
            # Example command: do something
            print("Command received:", cmd)
        else:
            print("Unknown command:", cmd)

if __name__ == "__main__":
    run_shell()
