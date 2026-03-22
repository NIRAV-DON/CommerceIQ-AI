from app import create_app
print("Starting the Flask application...")
app = create_app()

if __name__ == '__main__':
    app.run(debug=True)