import sqlite3
from datetime import datetime
import asyncio

conn = sqlite3.connect('records.db')
cursor = conn.cursor()
cursor.execute('SELECT itemName FROM items WHERE auctionID = ?', (1,))
itemNames = cursor.fetchall()
for item in itemNames:
    print(item[0])
