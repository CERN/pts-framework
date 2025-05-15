import yaml

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
    return result

def validate_field(doc, field_name, expected_type, faults, warnings, context, line_map, path=()):
    full_path = path + (field_name,)
    line_info = f"(line {line_map.get(full_path, '?')})"

    if field_name not in doc:
        faults.append(f"[{context}] Missing required field: '{field_name}' {line_info}")
        return

    value = doc[field_name]

    if value is None:
        # None is warning only for strings, fault for others
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


def validate_recipe_file(file_path):
    faults = []
    warnings = []

    with open(file_path, 'r') as f:
        content = f.read()

    try:
        docs_nodes = list(yaml.compose_all(content))
    except yaml.YAMLError as e:
        raise RecipeValidationError([f"YAML parsing error: {e}"], [])

    docs = list(yaml.safe_load_all(content))  # For actual content

    for i, (doc, node) in enumerate(zip(docs, docs_nodes)):
        if not isinstance(doc, dict):
            faults.append(f"[Document {i}] is not a dictionary (line {node.start_mark.line + 1})")
            continue

        line_map = extract_line_map(node)

        first_key = next(iter(doc), None)

        if first_key == "name":
            context = "Header"
            validate_field(doc, "version", str, faults, warnings, context, line_map)
            validate_field(doc, "description", str, faults, warnings, context, line_map)
            validate_field(doc, "main_sequence", str, faults, warnings, context, line_map)
            validate_field(doc, "globals", dict, faults, warnings, context, line_map)

        elif first_key == "sequence_name":
            context = "Sequence"
            validate_field(doc, "description", str, faults, warnings, context, line_map)
            validate_field(doc, "setup_steps", list, faults, warnings, context, line_map)

            if "steps" not in doc:
                line_info = f"(line {line_map.get(('steps',), '?')})"
                faults.append(f"[{context}] Missing required subsection: 'steps' {line_info}")

            for key in ["teardown_steps", "parameters", "outputs"]:
                validate_field(doc, key, list, faults, warnings, context, line_map)

            if "locals" not in doc:
                faults.append(f"[{context}] Missing 'locals' section")
            elif not isinstance(doc["locals"], dict):
                faults.append(f"[{context}] 'locals' should be a dictionary")
        else:
            line = node.start_mark.line + 1
            faults.append(f"[Document {i}] Unrecognized document type, first key: '{first_key}' (line {line})")

    if faults or warnings:
        print("❌ Validation completed with issues:")

        if faults:
            print("🛑 Faults:")
            for f in faults:
                print(" -", f)

        if warnings:
            print("⚠️ Warnings:")
            for w in warnings:
                print(" -", w)

        raise RecipeValidationError(faults, warnings)

    print("✅ Validation passed successfully.")

# Example usage:
# validate_recipe_file("recipes/recipeCRATE.yaml")


if __name__ == "__main__":
    try:
        validate_recipe_file("recipes/recipeCRATE.yaml")
    except Exception as e:
        print(f"❌ Validation failed: {e}")
