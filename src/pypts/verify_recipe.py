from pathlib import Path
import os
import yaml
from pypts.rules import RECIPE_HEADER_REQUIRED_FIELDS, RECIPE_SEQUENCE_REQUIRED_FIELDS, STEP_REQUIRED_FIELDS

class RecipeValidationError(Exception):
    def __init__(self, faults, warnings):
        self.faults = faults
        self.warnings = warnings
        super().__init__(f"Validation failed with {len(faults)} faults and {len(warnings)} warnings")

def extract_line_map(node, path=()):
    result = {}
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            key = key_node.value
            new_path = path + (key,)
            result[new_path] = key_node.start_mark.line + 1
            result.update(extract_line_map(value_node, new_path))
    elif isinstance(node, yaml.SequenceNode):
        for idx, item_node in enumerate(node.value):
            new_path = path + (idx,)
            result.update(extract_line_map(item_node, new_path))
    return result

def validate_field(doc, field_name, expected_type, faults, warnings, context, line_map, path=()):
    full_path = path + (field_name,)
    line_info = f"(line {line_map.get(full_path, '?')})"

    if field_name not in doc:
        faults.append(f"[{context}] Missing required field: '{field_name}' {line_info}")
        return

    value = doc[field_name]

    if value is None:
        if expected_type == str:
            warnings.append(f"[{context}] Field '{field_name}' is null {line_info}")
        else:
            faults.append(f"[{context}] Field '{field_name}' is null but expected type {expected_type.__name__} {line_info}")
        return

    if not isinstance(value, expected_type):
        faults.append(
            f"[{context}] Field '{field_name}' should be of type {expected_type.__name__}, "
            f"but got {type(value).__name__} {line_info}"
        )
        return

    if expected_type == str and not value.strip():
        warnings.append(f"[{context}] Field '{field_name}' is an empty string {line_info}")

def validate_step_fields(steps, faults, line_map, base_path=()):
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            faults.append(f"[Step {idx}] Step is not a dictionary")
            continue

        step_path = base_path + (idx,)
        step_line = line_map.get(step_path, '?')
        step_name = step.get("step_name", f"at index {idx}")
        context = f"Step {idx} ({step_name})"

        steptype = step.get("steptype")
        required_fields = STEP_REQUIRED_FIELDS.get(steptype, STEP_REQUIRED_FIELDS["default"])

        for field in required_fields:
            field_path = step_path + (field,)
            line = line_map.get(field_path, step_line)
            if field not in step:
                faults.append(f"[{context}] Missing required field: '{field}' (line {line})")

def validate_all_recipes_in_folder(folder_path):
    errors = []
    for filename in os.listdir(folder_path):
        if filename.endswith(".yaml") or filename.endswith(".yml"):
            full_path = os.path.join(folder_path, filename)
            try:
                validate_recipe_file(full_path)
            except RecipeValidationError as e:
                errors.append((filename, e))

    if errors:
        print("\n❌ Summary: Some recipe files failed validation.")
        for filename, e in errors:
            print(f" - {filename}: {len(e.faults)} faults, {len(e.warnings)} warnings")
            pass
        return False
    else:
        print("\n✅ All recipe files validated successfully.")
        return True

def validate_recipe_filepath(file_path):
    errors = []
    p = Path(file_path)
    filename = p.stem
    try:
        validate_recipe_file(file_path)
    except RecipeValidationError as e:
        errors.append((filename, e))

    if errors:
        print("\n❌ Summary: Some recipe files failed validation.")
        for filename, e in errors:
            print(f" - {filename}: {len(e.faults)} faults, {len(e.warnings)} warnings")
            pass
        return False
    else:
        print("\n✅ All recipe files validated successfully.")
        return True

def validate_recipe_file(filepath):
    faults = []
    warnings = []

    with open(filepath, 'r') as f:
        content = f.read()

    try:
        docs_nodes = list(yaml.compose_all(content))
    except yaml.YAMLError as e:
        raise RecipeValidationError([f"YAML parsing error in '{filepath}': {e}"], [])

    docs = list(yaml.safe_load_all(content))

    for i, (doc, node) in enumerate(zip(docs, docs_nodes)):
        if not isinstance(doc, dict):
            faults.append(f"[{filepath}, Document {i}] is not a dictionary (line {node.start_mark.line + 1})")
            continue

        line_map = extract_line_map(node)
        first_key = next(iter(doc), None)

        if first_key == "name":
            context = f"{filepath} Header"
            for field, expected_type in RECIPE_HEADER_REQUIRED_FIELDS.items():
                validate_field(doc, field, expected_type, faults, warnings, context, line_map)

        elif first_key == "sequence_name":
            context = f"{filepath} Sequence"
            for field, expected_type in RECIPE_SEQUENCE_REQUIRED_FIELDS.items():
                # For "steps" subsection, validate presence and content separately
                if field == "steps":
                    if field not in doc:
                        line_info = f"(line {line_map.get(('steps',), '?')})"
                        faults.append(f"[{context}] Missing required subsection: 'steps' {line_info}")
                    else:
                        validate_step_fields(doc["steps"], faults, line_map, base_path=("steps",))
                else:
                    validate_field(doc, field, expected_type, faults, warnings, context, line_map)

            if "locals" not in doc:
                faults.append(f"[{context}] Missing 'locals' section")
            elif not isinstance(doc["locals"], dict):
                faults.append(f"[{context}] 'locals' should be a dictionary")
        else:
            line = node.start_mark.line + 1
            faults.append(f"[{filepath}, Document {i}] Unrecognized document type, first key: '{first_key}' (line {line})")

    if faults or warnings:
        # print(f"❌ Validation for '{filepath}' completed with issues:")

        if faults:
            print("🛑 Faults:")
            for f in faults:
                print(" -", f)
                pass

        if warnings:
            print("⚠️ Warnings:")
            for w in warnings:
                print(" -", w)
                pass

        raise RecipeValidationError(faults, warnings)

    print(f"✅ Validation passed for '{filepath}'.")

def validate_recipe_string_variable(content):
    faults = []
    warnings = []

    try:
        docs_nodes = list(yaml.compose_all(content))
    except yaml.YAMLError as e:
        raise RecipeValidationError([f"YAML parsing error in : {e}"], [])

    docs = list(yaml.safe_load_all(content))

    for i, (doc, node) in enumerate(zip(docs, docs_nodes)):
        if not isinstance(doc, dict):
            faults.append(f"[, Document {i}] is not a dictionary (line {node.start_mark.line + 1})")
            continue

        line_map = extract_line_map(node)
        first_key = next(iter(doc), None)

        if first_key == "name":
            context = f"Header"
            for field, expected_type in RECIPE_HEADER_REQUIRED_FIELDS.items():
                validate_field(doc, field, expected_type, faults, warnings, context, line_map)

        elif first_key == "sequence_name":
            context = f"Sequence"
            for field, expected_type in RECIPE_SEQUENCE_REQUIRED_FIELDS.items():
                # For "steps" subsection, validate presence and content separately
                if field == "steps":
                    if field not in doc:
                        line_info = f"(line {line_map.get(('steps',), '?')})"
                        faults.append(f"[{context}] Missing required subsection: 'steps' {line_info}")
                    else:
                        validate_step_fields(doc["steps"], faults, line_map, base_path=("steps",))
                else:
                    validate_field(doc, field, expected_type, faults, warnings, context, line_map)

            if "locals" not in doc:
                faults.append(f"[{context}] Missing 'locals' section")
            elif not isinstance(doc["locals"], dict):
                faults.append(f"[{context}] 'locals' should be a dictionary")
        else:
            line = node.start_mark.line + 1
            faults.append(
                f"[Document {i}] Unrecognized document type, first key: '{first_key}' (line {line})")

    if faults or warnings:
        print(f"❌ Validation for recipe completed with issues:")
        if faults:
            print("🛑 Faults:")
            for f in faults:
                print(" -", f)
                return False
        if warnings:
            print("⚠️ Warnings:")
            for w in warnings:
                print(" -", w)
                pass
        raise RecipeValidationError(faults, warnings)
    else:
        print(f"✅ No faults, warnings.")

    print(f"✅ Validation passed for the variable recipe.")
    return True



if __name__ == "__main__":
    import sys
    folder = sys.argv[1] if len(sys.argv) > 1 else "recipes/"

    try:
        if (validate_all_recipes_in_folder(folder)):
            print("✅ Recipe file validated successfully.")
        else:
            print("❌ Summary: Recipe file failed the validation!")
    except Exception as e:
        print(f"❌ Unhandled expception while validating the recipe: {e}")

    #todo - fix the prints, add a flag that would determine if functions shall print on the stdout or not.
    # For now, the prints are just commented

    # # example usage on specific recipe
    # path = "recipes/simple_recipe_GOLDEN.yml"
    # path = "recipes/simple_recipe.yml"
    # validate_recipe(path)