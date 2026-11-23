import uml_engine

# Give the engine a math problem in standard notation
problem = "2 + 2 * 5"

# Run it through the engine
result, node, notation, trace = uml_engine.evaluate(problem)

# Print the result using the engine's formatting tool
print(f"Engine Output: {uml_engine.fmt(result)}")