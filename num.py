# 1, 2, 3 
# 4, 5, 6

def adder(num1: list = [], num2: list = []) -> int:
    list1 = reversed(num1)
    list2 = reversed(num2)
    number1 = ""
    number2 = ""

    for i in list1:
        number1 += str(i)
    for i in list2:
        number2 += str(i)

    return int(number1) + int(number2)

tot = adder([1, 2, 3], [4, 5, 6])
print(tot)