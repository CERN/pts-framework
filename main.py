from sequence import Sequence
import logging

logging.basicConfig(level=logging.INFO)


seq = Sequence("my_sequence.yaml", {"target_value": 45})
result = seq.run()
print(result)
print("--- VARIABLES ---")
for var, val in seq._variables.items():
    print(var, val)
print("--- PARAMETERS ---")
for param, val in seq._parameters.items():
    print(param, val)
print("--- OUTPUTS ---")
for output, val in seq._outputs.items():
    print(output, val)