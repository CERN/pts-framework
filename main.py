from sequence import Sequence
import logging

logging.basicConfig(level=logging.INFO)


seq = Sequence("my_sequence.yaml", {})
result = seq.run()
print(result)
print("--- VARIABLES ---")
for var, val in seq._variables.items():
    print(var, val)