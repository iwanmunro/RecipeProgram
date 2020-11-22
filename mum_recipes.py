from tkinter import *
from tkinter.ttk import *

# TO DO
# - research if photocopy concept could work,
# 	could have name of photo input by user and then use that to create link to photocopy
# - add in bunch of recipes and test
# - EXTRA FUNCTIONALITY - Multiple search terms?

class tkinterGUI:
	def load_recipes(self):
		"""Loads the recipes in, needs to be done to look at recipe ingredients"""
		recipes = []
		recipe_txt = open("recipes.txt", "r")
		for i in recipe_txt:
			recipes.append([i])
		self.recipes = recipes

	def save_recipe(self):
		"""Function that produces the save to recipes.txt of a new recipe"""
		recipe = [self.a0.get(), self.a1.get(), self.a2.get(), self.a3.get(), self.a4.get(),
				  self.a5.get(), self.a6.get(), self.a7.get(), self.a8.get(),
				  self.a9.get(), self.a10.get(), self.a11.get(), self.a12.get(),
				  self.a13.get(), self.a14.get(), self.a15.get(), self.a16.get(),
				  self.a17.get(), self.a18.get(), self.a19.get(), self.a20.get()]
		with open('recipes.txt', 'a+') as recipes:
			recipes.write("\n")
			for i in recipe:
				recipes.write(i+",")

	def search_recipe(self):
		"""Search function"""
		self.output_box.delete(0,END)
		with open('recipes.txt', 'r') as recipes:
			for i in recipes:
				if i.lower().find(self.search_entry.get().lower()) != -1:
					self.output_box.insert(END,i.split(',')[0])
	
	def delete_recipe(self):
		"""function that deletes recipes selected but also needs to update dropdown menu or
		kick off function which deletes dropdown"""
		for i in self.recipes:
			print(i)
			if i[0].lower().find(self.output_box.get(ACTIVE).lower()) != -1:
				self.recipes.remove(i)
				break
		file = open('recipes.txt','r+')
		file.truncate(0)
		file.close()
		with open('recipes.txt', 'w') as recipes:
			for i in self.recipes:
				for j in i[0].split(','):
					recipes.write(j)
		self.output_box.delete(0,END)

	def find_photocopy(self):
		"""Take the recipe and find the photocopy for picture and method"""
		pass

	def recipe_window(self):
		"""tkinter window for specific recipe selection"""
		for i in self.recipes:
			if i[0].lower().find(self.output_box.get(ACTIVE).lower()) != -1:
				recipe = i
				break

		newWindow = Toplevel(master)
		newWindow.geometry("500x500")
		btn_return = Button(newWindow, text="Return", command=newWindow.destroy)
		btn_return.place(x=160,y=450)
		btn_photo = Button(newWindow, text="Photocopy", command=self.find_photocopy)
		btn_photo.place(x=260,y=450)
		Label(newWindow, text=recipe[0].split(',')[0], font=16).pack(pady=10)
		listbox = Listbox(newWindow, height=24, width=75)
		listbox.pack()

		for i in recipe[0].split(',')[1:]:
			listbox.insert(END,i)

	def save_window(self):
		"""tkinter window for saving a new recipe"""
		newWindow = Toplevel(master)
		newWindow.geometry("500x500")
		btn_return = Button(newWindow, text="Return", command=newWindow.destroy)
		btn_return.pack(pady=10)
		btn_return.place(x=260,y=450)

		Label(newWindow, text="Recipe Import Window", font=20).pack()
		btn_save = Button(newWindow, text="Save", command=self.save_recipe)
		btn_save.pack(pady=10)
		btn_save.place(x=160,y=450)

		label = Label(newWindow, text ="Name of Dish")
		label.pack(pady=10)
		label.place(x=20,y=30)
		label = Label(newWindow, text ="Ingredients")
		label.pack(pady=10)
		label.place(x=20,y=60)
		self.a0 = Entry(newWindow)
		self.a0.place(x=195,y=30)
		self.a1 = Entry(newWindow)
		self.a1.place(x=115,y=60)
		self.a2 = Entry(newWindow)
		self.a2.place(x=115,y=85)
		self.a3 = Entry(newWindow)
		self.a3.place(x=115,y=110)
		self.a4 = Entry(newWindow)
		self.a4.place(x=115,y=135)
		self.a5 = Entry(newWindow)
		self.a5.place(x=115,y=160)
		self.a6 = Entry(newWindow)
		self.a6.place(x=115,y=185)
		self.a7 = Entry(newWindow)
		self.a7.place(x=115,y=210)
		self.a8 = Entry(newWindow)
		self.a8.place(x=115,y=235)
		self.a9 = Entry(newWindow)
		self.a9.place(x=115,y=260)
		self.a10 = Entry(newWindow)
		self.a10.place(x=115,y=285)
		self.a11 = Entry(newWindow)
		self.a11.place(x=260,y=60)
		self.a12 = Entry(newWindow)
		self.a12.place(x=260,y=85)
		self.a13 = Entry(newWindow)
		self.a13.place(x=260,y=110)
		self.a14 = Entry(newWindow)
		self.a14.place(x=260,y=135)
		self.a15 = Entry(newWindow)
		self.a15.place(x=260,y=160)
		self.a16 = Entry(newWindow)
		self.a16.place(x=260,y=185)
		self.a17 = Entry(newWindow)
		self.a17.place(x=260,y=210)
		self.a18 = Entry(newWindow)
		self.a18.place(x=260,y=235)
		self.a19 = Entry(newWindow)
		self.a19.place(x=260,y=260)
		self.a20 = Entry(newWindow)
		self.a20.place(x=260,y=285)

	def search_window(self):
		"""tkinter window for searching for specific recipes"""
		newWindow = Toplevel(master)
		newWindow.geometry("500x500")
		btn_delete = Button(newWindow, text="Delete", command=self.delete_recipe)
		btn_delete.place(x=200, y=465)
		btn_return = Button(newWindow, text="Return", command=newWindow.destroy)
		btn_return.place(x=300, y=465)
		btn_select = Button(newWindow, text="Select", command=self.recipe_window)
		btn_select.place(x=100, y=465)
		Label(newWindow, text="Recipe Search Window", font=20).pack()

		self.search_entry = Entry(newWindow, width=50)
		self.search_entry.pack(pady=10)
		self.search_entry.place(x=50, y=30)
		btn_search = Button(newWindow, text="Search", command=self.search_recipe)
		btn_search.place(x=380, y=28)

		frame = Frame(newWindow, height=25, width=200)
		frame.place(x=20, y=75)

		scrollbar = Scrollbar(frame)
		scrollbar.pack(side=RIGHT, fill=Y)

		self.output_box = Listbox(frame, yscrollcommand=scrollbar.set, height=24, width=75)
		self.output_box.pack()

		scrollbar.config(command=self.output_box.yview)

if __name__ == '__main__':
	# creates a Tk() object
	master = Tk()
	master.title("Mums Recipe Program")
	master.geometry("300x300")
	label = Label(master, text ="Mums Recipe Program", font=20)
	label.pack(pady=10)

	# a button widget which will open a new window on button click
	tkinterGUI = tkinterGUI()
	btn_save = Button(master, text="Save Recipe", command=tkinterGUI.save_window, width=30)
	btn_save.pack(pady=10)
	btn_search = Button(master, text="Search Recipe", command=tkinterGUI.search_window, width=30)
	btn_search.pack(pady=10)
	btn_load = Button(master, text="Load Recipes", command=tkinterGUI.load_recipes, width=30)
	btn_load.pack(pady=10)

	label = Label(master, text ="**Load the recipes before searching**")
	label.pack(pady=10)

	quit = Button(master, text="QUIT", command=master.destroy)
	quit.pack(side="bottom")

	mainloop()
