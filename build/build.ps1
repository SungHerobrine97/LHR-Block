pyinstaller -F -w --onedir `
--add-data "engine/*.py;engine" `
--add-data "content/presets/*.json;content/presets"  `
--add-data "export/*.json;export" `
main.py `
--name "Laharoi Block Story Editor" `
--icon "icons.ico"