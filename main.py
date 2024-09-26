from sequence import Sequence
import logging
import recipe

logging.basicConfig(level=logging.INFO)



seq = Sequence("my_sequence.yaml", {"target_value": 45})
result = seq.run()

print(result)
print("--- PARAMETERS ---")
for param, val in seq.parameters.items():
    print(param, val)
print("--- LOCALS ---")
for var, val in seq.locals.items():
    print(var, val)
print("--- OUTPUTS ---")
for output, val in seq.outputs.items():
    print(output, val)

# recipe = recipe.Recipe("my_sequence copy.yaml")