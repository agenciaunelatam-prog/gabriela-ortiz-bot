import os
import json
import requests

FACEBOOK_TOKEN = os.environ["FACEBOOK_TOKEN"]
FACEBOOK_PAGE_ID = os.environ["FACEBOOK_PAGE_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
WP_URL = os.environ["WP_URL"]
WP_USER = os.environ["WP_USER"]
WP_PASSWORD = os.environ["WP_PASSWORD"]

LAST_POST_FILE = "last_post.txt"

GEMINI_PROMPT = """Sos un redactor de prensa profesional. Transformá el siguiente texto de una publicación de Facebook en una gacetilla de prensa en español.

La gacetilla debe tener este formato exacto:
TÍTULO: (título llamativo en estilo periodístico)
COPETE: (una oración resumen)
CUERPO: (2 o 3 párrafos en tercera persona, estilo periodístico)
CIERRE: (datos de contacto si los hay en el texto, o una oración de cierre institucional)

Publicación de Facebook:
{post_text}"""


def get_last_processed_id():
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r") as f:
            return f.read().strip()
    return None


def save_last_processed_id(post_id):
    with open(LAST_POST_FILE, "w") as f:
        f.write(post_id)


def get_latest_facebook_post():
    url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/posts"
    params = {
        "fields": "id,message,created_time",
        "limit": 5,
        "access_token": FACEBOOK_TOKEN,
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    posts = data.get("data", [])
    # retorna el post más reciente que tenga texto
    for post in posts:
        if post.get("message"):
            return post
    return None


def generate_press_release(post_text):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": GEMINI_PROMPT.format(post_text=post_text)}
                ]
            }
        ]
    }
    response = requests.post(url, json=payload)
    response.raise_for_status()
    result = response.json()
    return result["candidates"][0]["content"]["parts"][0]["text"]


def parse_press_release(text):
    """Extrae título y cuerpo del texto generado por Gemini."""
    title = ""
    body_lines = []
    for line in text.split("\n"):
        if line.startswith("TÍTULO:"):
            title = line.replace("TÍTULO:", "").strip()
        else:
            body_lines.append(line)
    body = "\n".join(body_lines).strip()
    # convierte saltos de línea a párrafos HTML
    paragraphs = [f"<p>{p.strip()}</p>" for p in body.split("\n\n") if p.strip()]
    return title, "\n".join(paragraphs)


def publish_to_wordpress(title, content):
    url = f"{WP_URL}/wp-json/wp/v2/posts"
    payload = {
        "title": title,
        "content": content,
        "status": "draft",  # cambiá a "publish" para publicar directo
    }
    response = requests.post(url, json=payload, auth=(WP_USER, WP_PASSWORD))
    response.raise_for_status()
    return response.json()["link"]


def main():
    print("Buscando nuevos posts en Facebook...")
    post = get_latest_facebook_post()

    if not post:
        print("No se encontraron posts con texto.")
        return

    post_id = post["id"]
    last_id = get_last_processed_id()

    if post_id == last_id:
        print("No hay posts nuevos desde la última ejecución.")
        return

    print(f"Nuevo post encontrado: {post_id}")
    print(f"Texto: {post['message'][:100]}...")

    print("Generando gacetilla con Gemini...")
    press_release = generate_press_release(post["message"])

    title, content = parse_press_release(press_release)
    print(f"Título generado: {title}")

    print("Publicando en WordPress...")
    wp_link = publish_to_wordpress(title, content)
    print(f"Borrador creado: {wp_link}")

    save_last_processed_id(post_id)
    print("Listo.")


if __name__ == "__main__":
    main()
