import os
import time
import requests

FACEBOOK_TOKEN = os.environ["FACEBOOK_TOKEN"]
FACEBOOK_PAGE_ID = os.environ["FACEBOOK_PAGE_ID"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
WP_URL = os.environ["WP_URL"].rstrip("/")
WP_USER = os.environ["WP_USER"]
WP_PASSWORD = os.environ["WP_PASSWORD"]

PROCESSED_FILE = "processed_ids.txt"

PROMPT_GACETILLA = """Sos un redactor de prensa institucional que trabaja para Gabriela Ortiz, concejal de la ciudad de Santiago del Estero, Argentina.

Transformá el siguiente texto de una publicación de Facebook en una gacetilla de prensa en español.

Tono: institucional, propositivo, con una conclusión motivacional e inspiradora al final.

Estructura (NO escribas los nombres de las secciones, redactá todo como texto corrido):
- Una oración inicial que resuma el hecho principal
- Dos o tres párrafos de desarrollo en tercera persona, estilo periodístico
- Un párrafo final con conclusión motivacional e inspiradora

Reglas de redacción:
- NO uses las palabras "copete", "cuerpo", "cierre" ni ningún título de sección
- Evitá repetir la misma palabra o frase clave más de dos veces en todo el texto — usá sinónimos y variaciones
- Gabriela Ortiz es siempre la PROTAGONISTA: ella actúa, participa, impulsa, acompaña. Nunca es una observadora externa ni alguien ajeno a su ciudad
- Presentala como parte activa y comprometida de Santiago del Estero: cercana a su gente, presente en los momentos importantes, representando genuinamente a sus vecinos
- Evitá frases genéricas como "en la localidad de...", "se unen a la conmemoración" o similares que la desvinculen del hecho
- El TÍTULO va al principio, en una línea separada con el prefijo TÍTULO:

Publicación de Facebook:
{post_text}"""

PROMPT_FILTRO = """Analizá la siguiente publicación de Facebook de una concejal.

Respondé SOLO con una de estas dos palabras: PUBLICAR o IGNORAR.

Regla: respondé IGNORAR únicamente si el posteo informa que se realizó la sesión semanal del Concejo Deliberante pero NO menciona ninguna acción concreta, proyecto aprobado, reconocimiento, tema especial o hecho relevante tratado en esa sesión. En todos los demás casos, respondé PUBLICAR.

Publicación:
{post_text}"""


def load_processed_ids():
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, "r") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def save_processed_id(post_id):
    with open(PROCESSED_FILE, "a") as f:
        f.write(post_id + "\n")


def get_page_token():
    """Obtiene el access token específico de la página usando el token de sistema."""
    url = "https://graph.facebook.com/v19.0/me/accounts"
    params = {"access_token": FACEBOOK_TOKEN}
    response = requests.get(url, params=params)
    print(f"GET /me/accounts: status {response.status_code}")
    if not response.ok:
        print(f"  Error: {response.text[:300]}")
        return None
    accounts = response.json().get("data", [])
    print(f"Páginas accesibles: {len(accounts)}")
    for acc in accounts:
        print(f"  - ID: {acc.get('id')} | Nombre: {acc.get('name')}")
        if acc.get("id") == FACEBOOK_PAGE_ID or acc.get("name", "").lower().replace(" ", "") in FACEBOOK_PAGE_ID.lower():
            print(f"  → Usando token de página para: {acc.get('name')}")
            return acc.get("access_token")
    # si no matchea, usar el primero disponible
    if accounts:
        print(f"  → Usando primera página disponible: {accounts[0].get('name')}")
        return accounts[0].get("access_token"), accounts[0].get("id")
    return None


def get_facebook_posts(limit=20):
    fields = "id,message,story,created_time,full_picture,attachments{media,subattachments,type,url}"

    # intentar obtener token de página
    page_token_result = get_page_token()
    if page_token_result and isinstance(page_token_result, tuple):
        page_token, page_id = page_token_result
    elif page_token_result:
        page_token = page_token_result
        page_id = FACEBOOK_PAGE_ID
    else:
        page_token = FACEBOOK_TOKEN
        page_id = FACEBOOK_PAGE_ID

    for endpoint in ["feed", "posts"]:
        url = f"https://graph.facebook.com/v19.0/{page_id}/{endpoint}"
        params = {"fields": fields, "limit": limit, "access_token": page_token}
        response = requests.get(url, params=params)
        print(f"Probando /{endpoint}: status {response.status_code}")
        if response.ok:
            posts = response.json().get("data", [])
            print(f"Posts obtenidos con /{endpoint}: {len(posts)}")
            if posts:
                for p in posts:
                    text = p.get("message") or p.get("story") or ""
                    img = p.get("full_picture", "")
                    print(f"  [{p.get('created_time','')[:10]}] texto: {repr(text[:60])} | imagen: {'SI' if img else 'NO'}")
                return posts
        else:
            print(f"  Error: {response.text[:200]}")
    print("Ningún endpoint devolvió posts.")
    return []


def llamar_groq(prompt, temperatura=0.7):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperatura,
    }
    for intento in range(3):
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 429:
            espera = 20 * (intento + 1)
            print(f"Límite Groq alcanzado, esperando {espera}s...")
            time.sleep(espera)
            continue
        if not response.ok:
            print(f"Error Groq: {response.status_code} - {response.text[:200]}")
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    raise Exception("Groq no respondió después de 3 intentos")


def debe_publicar(post_text):
    respuesta = llamar_groq(PROMPT_FILTRO.format(post_text=post_text), temperatura=0).strip().upper()
    print(f"Filtro: {respuesta}")
    return "PUBLICAR" in respuesta


def generate_press_release(post_text):
    return llamar_groq(PROMPT_GACETILLA.format(post_text=post_text))


def parse_press_release(text):
    title = ""
    body_lines = []
    for line in text.split("\n"):
        if line.startswith("TÍTULO:"):
            title = line.replace("TÍTULO:", "").strip()
        else:
            body_lines.append(line)
    body = "\n".join(body_lines).strip()
    paragraphs = [f"<p>{p.strip()}</p>" for p in body.split("\n\n") if p.strip()]
    return title or "Sin título", "\n".join(paragraphs)


def upload_image_to_wordpress(image_url):
    """Descarga la imagen de Facebook y la sube a WordPress. Retorna el media_id o None."""
    try:
        img_response = requests.get(image_url, timeout=15)
        img_response.raise_for_status()
        content_type = img_response.headers.get("Content-Type", "image/jpeg")
        ext = "jpg" if "jpeg" in content_type else content_type.split("/")[-1]
        filename = f"fb_image.{ext}"

        wp_media_url = f"{WP_URL}/wp-json/wp/v2/media"
        headers = {"Content-Disposition": f'attachment; filename="{filename}"', "Content-Type": content_type}
        resp = requests.post(
            wp_media_url,
            headers=headers,
            data=img_response.content,
            auth=(WP_USER, WP_PASSWORD),
        )
        if not resp.ok:
            print(f"Error subiendo imagen a WP: {resp.status_code} - {resp.text[:200]}")
            return None
        media = resp.json()
        print(f"Imagen subida a WordPress: {media.get('source_url', '')}")
        return media["id"], media.get("source_url", "")
    except Exception as e:
        print(f"No se pudo subir la imagen: {e}")
        return None


def publish_to_wordpress(title, content, featured_media_id=None, post_date=None):
    url = f"{WP_URL}/wp-json/wp/v2/posts"
    payload = {"title": title, "content": content, "status": "publish"}
    if featured_media_id:
        payload["featured_media"] = featured_media_id
    if post_date:
        # WordPress espera formato: 2026-06-03T14:00:00
        payload["date"] = post_date[:19]
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, json=payload, headers=headers, auth=(WP_USER, WP_PASSWORD))
    if not response.ok:
        print(f"Error WordPress: {response.status_code} - {response.text[:300]}")
    response.raise_for_status()
    return response.json().get("link", "sin link")


def collect_image_urls(post):
    """Recolecta todas las URLs de imágenes del post."""
    images = []
    # imagen principal
    if post.get("full_picture"):
        images.append(post["full_picture"])
    # imágenes adicionales de attachments
    attachments = post.get("attachments", {}).get("data", [])
    for att in attachments:
        media = att.get("media", {})
        img = media.get("image", {})
        url = img.get("src", "")
        if url and url not in images:
            images.append(url)
        # subattachments (álbumes)
        for sub in att.get("subattachments", {}).get("data", []):
            sub_url = sub.get("media", {}).get("image", {}).get("src", "")
            if sub_url and sub_url not in images:
                images.append(sub_url)
    return images


def main():
    print("=== Bot Gabriela Ortiz: Facebook → WordPress ===\n")
    processed_ids = load_processed_ids()
    print(f"Posts ya procesados: {len(processed_ids)}\n")

    posts = get_facebook_posts(limit=20)

    nuevos = [p for p in posts if p["id"] not in processed_ids]
    nuevos = nuevos[:10]
    print(f"\nPosts nuevos a procesar: {len(nuevos)}")

    if not nuevos:
        print("No hay posts nuevos.")
        return

    # del más viejo al más nuevo
    for post in reversed(nuevos):
        post_id = post["id"]
        text = post.get("message") or post.get("story") or ""
        fecha = post.get("created_time", "")[:10]

        print(f"\n--- Procesando post {post_id} ({fecha}) ---")

        if not text:
            print("Sin texto, omitiendo.")
            save_processed_id(post_id)
            continue

        print(f"Texto: {text[:120]}...")

        # filtrar posts de sesión sin contenido relevante
        if not debe_publicar(text):
            print("Post omitido: sesión del Concejo sin contenido relevante.")
            save_processed_id(post_id)
            continue

        # generar gacetilla
        print("Generando gacetilla con Groq...")
        press_release = generate_press_release(text)
        title, body_html = parse_press_release(press_release)
        print(f"Título: {title}")

        # subir imágenes a WordPress
        image_urls = collect_image_urls(post)
        print(f"Imágenes encontradas: {len(image_urls)}")

        featured_media_id = None
        extra_images_html = ""

        for i, img_url in enumerate(image_urls[:3]):
            try:
                result = upload_image_to_wordpress(img_url)
                if result:
                    media_id, source_url = result
                    if i == 0:
                        featured_media_id = media_id
                    extra_images_html += f'<figure><img src="{source_url}" /></figure>\n'
            except Exception as e:
                print(f"Imagen {i+1} omitida: {e}")

        # armar contenido final
        content = body_html
        if extra_images_html:
            content += "\n" + extra_images_html

        # publicar en WordPress
        print("Publicando en WordPress...")
        wp_link = publish_to_wordpress(title, content, featured_media_id, post_date=post.get("created_time"))
        print(f"Borrador creado: {wp_link}")

        save_processed_id(post_id)
        time.sleep(5)

    print("\n=== Listo ===")


if __name__ == "__main__":
    main()
