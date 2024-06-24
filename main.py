from sequence import Sequence
import logging

logging.basicConfig(level=logging.INFO)


seq = Sequence("my_sequence.yaml", {"target_value": 45})
result = seq.run()

print(result)
print("--- PARAMETERS ---")
for param, val in seq.parameters.items():
    print(param, val)
print("--- VARIABLES ---")
for var, val in seq.variables.items():
    print(var, val)
print("--- OUTPUTS ---")
for output, val in seq.outputs.items():
    print(output, val)
    