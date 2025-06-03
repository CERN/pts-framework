# SPDX-FileCopyrightText: 2025 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

print("Hello!")

this_number = 3

def change_number(new_number):
    global this_number
    print(f"The new number is {new_number}")
    this_number = new_number

def get_number():
    print(f"Reading the number: {this_number}")
    return this_number
