pyinstaller -F -w --onedir `
--add-data "engine/*.py;engine" `
--add-data "content/presets/*.json;content/presets"  `
main.py `
--name "Laharoi Block Story Editor"