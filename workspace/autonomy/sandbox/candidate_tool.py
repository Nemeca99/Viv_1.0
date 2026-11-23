def letter_to_word_ratio(sentence):
    # Split the sentence into words
    words = sentence.split()
    
    # Calculate the letter-to-word ratio
    letters = 0
    for word in words:
        letters += len(word) / len(sentence)
        
    return letters

# Example usage
sentence = "Viv, write a function that takes any sentence, breaks it into words, and calculates the exact letter-to-word ratio."
result = letter_to_word_ratio(sentence)
print(f"The letter-to-word ratio is {result:.2f}")