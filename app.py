from flask import Flask, request, jsonify, render_template, session, redirect, url_for
import psycopg2
import os
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "secret123"

# ================= CONFIG UPLOAD =================
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ================= DB CONNECTION =================
def get_conn():
    DATABASE_URL = os.environ.get(
        "DATABASE_URL",
        "postgresql://flask_db_og3x_users:..."
    )
    return psycopg2.connect(DATABASE_URL, sslmode='require')
# ================= CALCUL STATS =================
def calculer_stats_produits(produits):
    total_vues   = sum(p['vues']   for p in produits)
    total_clicks = sum(p['clicks'] for p in produits)
    total_likes  = sum(p['likes']  for p in produits)
    return {
        'total_produits' : len(produits),
        'total_vues'     : total_vues,
        'total_clicks'   : total_clicks,
        'total_likes'    : total_likes,
        'moyenne_vues'   : round(total_vues / len(produits), 2) if produits else 0,
        'taux_engagement': round(total_clicks / total_vues * 100, 2) if total_vues > 0 else 0,
    }

# ================= LECTURE PRODUITS + STATS =================
def lire_produits_avec_stats():
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        SELECT
            p.id_produit,
            p.nom_produit,
            p.prix_produit,
            p.stock,
            p.image_produit,
            COALESCE(SUM(s.vues),   0) AS vues,
            COALESCE(SUM(s.clicks), 0) AS clicks,
            COALESCE(SUM(s.likes),  0) AS likes
        FROM produit p
        LEFT JOIN stats_produit s ON p.id_produit = s.produit_id
        GROUP BY p.id_produit, p.nom_produit, p.prix_produit, p.stock, p.image_produit
        ORDER BY p.id_produit DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    produits = []
    for r in rows:
        image  = ""
        if r[4]:
            image = "/" + r[4].replace("\\", "/")
        vues   = int(r[5])
        clicks = int(r[6])
        likes  = int(r[7])
        taux   = round(clicks / vues * 100, 2) if vues > 0 else 0
        produits.append({
            "id"    : r[0],
            "nom"   : r[1],
            "prix"  : float(r[2]),
            "stock" : r[3],
            "image" : image,
            "vues"  : vues,
            "clicks": clicks,
            "likes" : likes,
            "taux"  : taux,
        })
    return produits

# ================= ASSURER CONTRAINTE UNIQUE stats_produit =================
def assurer_contrainte_unique():
    """Crée la contrainte UNIQUE (produit_id, user_id) si elle n'existe pas."""
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'uq_stats_produit_user'
                ) THEN
                    ALTER TABLE stats_produit
                    ADD CONSTRAINT uq_stats_produit_user
                    UNIQUE (produit_id, user_id);
                END IF;
            END $$;
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Contrainte UNIQUE stats_produit OK")
    except Exception as e:
        print("⚠️  assurer_contrainte_unique:", e)

# ================= CRÉER TABLE FOLLOWS si elle n'existe pas =================
def create_tables():
    conn = get_conn()
    cur = conn.cursor()

    # TABLE USERS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id_users SERIAL PRIMARY KEY,
            name TEXT,
            email TEXT UNIQUE,
            password TEXT,
            role TEXT,
            code_secret TEXT
        );
    """)

    # TABLE PRODUIT
    cur.execute("""
        CREATE TABLE IF NOT EXISTS produit (
            id_produit SERIAL PRIMARY KEY,
            nom_produit TEXT,
            description_produit TEXT,
            prix_produit FLOAT,
            stock INT,
            image_produit TEXT
        );
    """)

    # TABLE STATS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stats_produit (
            id SERIAL PRIMARY KEY,
            produit_id INT,
            user_id INT,
            vues INT DEFAULT 0,
            clicks INT DEFAULT 0,
            likes INT DEFAULT 0
        );
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Tables créées")
# ================================================================
#  ROUTES
# ================================================================

# ================= INDEX =================
@app.route('/')
def index():
    return render_template('index.html')

# ================= REGISTER =================
@app.route('/register', methods=['POST'])
def register():
    data        = request.json
    name        = data.get('name')
    email       = data.get('email')
    password    = data.get('password')
    role        = data.get('role', 'client')
    code_secret = data.get('code_secret')

    if not name or not email or not password:
        return jsonify({"error": "Champs obligatoires manquants"}), 400
    if role == 'admin' and not code_secret:
        return jsonify({"error": "Code admin requis"}), 400

    hashed_password = generate_password_hash(password)
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("SELECT id_users FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            cur.close(); conn.close()
            return jsonify({"error": "Cet email est déjà utilisé"}), 409
        cur.execute("""
            INSERT INTO users (name, email, password, role, code_secret)
            VALUES (%s, %s, %s, %s, %s)
        """, (name, email, hashed_password, role, code_secret))
        conn.commit(); cur.close(); conn.close()
        return jsonify({"message": "Inscription réussie"})
    except Exception as e:
        print("ERREUR REGISTER:", e)
        return jsonify({"error": "Erreur serveur"}), 500

# ================= LOGIN =================
@app.route('/login', methods=['POST'])
def login():
    data     = request.json
    email    = data.get('email')
    password = data.get('password')
    role_req = data.get('role', 'client')

    if not email or not password:
        return jsonify({"error": "Email et mot de passe requis"}), 400
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("SELECT id_users, name, password, role FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        cur.close(); conn.close()

        if not user:
            return jsonify({"error": "Email incorrect"}), 401
        if not check_password_hash(user[2], password):
            return jsonify({"error": "Mot de passe incorrect"}), 401
        if user[3] != role_req:
            return jsonify({"error": f"Ce compte n'est pas un compte {role_req}"}), 403

        session['user_id'] = user[0]
        session['name']     = user[1]
        session['role']     = user[3]

        return jsonify({"redirect": "/admin" if user[3] == 'admin' else "/client"})
    except Exception as e:
        print("ERREUR LOGIN:", e)
        return jsonify({"error": str(e)}), 500

# ================= LOGOUT =================
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# ================= PAGES =================
@app.route('/admin')
def admin_home():
    if 'role' not in session or session['role'] != 'admin':
        return redirect('/')
    return render_template('admin.html')

@app.route('/client')
def client_home():
    if 'role' not in session or session['role'] != 'client':
        return redirect('/')
    return render_template('client.html')

@app.route('/analyse')
def analyse():
    if 'role' not in session or session['role'] != 'admin':
        return redirect('/')
    produits = lire_produits_avec_stats()
    stats    = calculer_stats_produits(produits)
    return render_template('analyse.html', produits=produits, stats=stats)

# ================= GET PRODUITS =================
@app.route('/api/produits', methods=['GET'])
def get_produits():
    try:
        return jsonify(lire_produits_avec_stats())
    except Exception as e:
        print("ERREUR PRODUITS:", e)
        return jsonify([])

# ================= ADD PRODUIT =================
@app.route('/api/produits', methods=['POST'])
def add_produit():
    if 'role' not in session or session['role'] != 'admin':
        return jsonify({"error": "Non autorisé"}), 403
    try:
        if request.is_json:
            data        = request.json
            nom         = data.get('nom')
            prix        = float(data.get('prix', 0))
            stock       = int(data.get('stock', 0))
            description = data.get('description', '')
            image_path  = None
        else:
            nom         = request.form.get('nom')
            prix        = float(request.form.get('prix', 0))
            stock       = int(request.form.get('stock', 0))
            description = request.form.get('description', '')
            image_path  = None
            file = request.files.get('image')
            if file and file.filename != "":
                filename   = secure_filename(file.filename)
                filepath   = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                image_path = f"static/uploads/{filename}"

        if not nom:
            return jsonify({"error": "Le nom du produit est requis"}), 400

        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO produit (nom_produit, description_produit, prix_produit, stock, image_produit)
            VALUES (%s, %s, %s, %s, %s)
        """, (nom, description, prix, stock, image_path))
        conn.commit(); cur.close(); conn.close()
        return jsonify({"message": "Produit ajouté avec succès"})
    except Exception as e:
        print("ERREUR AJOUT:", e)
        return jsonify({"error": str(e)}), 500

@app.route('/api/produits/<int:produit_id>', methods=['PUT'])
def update_produit(produit_id):
    if 'role' not in session or session['role'] != 'admin':
        return jsonify({"error": "Non autorisé"}), 403

    try:
        nom   = request.form.get('nom')
        prix  = request.form.get('prix')
        stock = request.form.get('stock')
        desc  = request.form.get('description')

        if not nom:
            return jsonify({"error": "Le nom est requis"}), 400

        prix  = float(prix) if prix else 0
        stock = int(stock) if stock else 0

        image_path = None
        file = request.files.get('image')

        if file and file.filename:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            image_path = f"static/uploads/{filename}"

        conn = get_conn()
        cur  = conn.cursor()

        if image_path:
            cur.execute("""
                UPDATE produit
                SET nom_produit=%s, prix_produit=%s, stock=%s,
                    description_produit=%s, image_produit=%s
                WHERE id_produit=%s
            """, (nom, prix, stock, desc, image_path, produit_id))
        else:
            cur.execute("""
                UPDATE produit
                SET nom_produit=%s, prix_produit=%s, stock=%s,
                    description_produit=%s
                WHERE id_produit=%s
            """, (nom, prix, stock, desc, produit_id))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"message": "Produit modifié avec succès"})

    except Exception as e:
        print("ERREUR UPDATE:", e)
        return jsonify({"error": str(e)}), 500

@app.route('/api/produits/<int:produit_id>', methods=['DELETE'])
def delete_produit(produit_id):
    if 'role' not in session or session['role'] != 'admin':
        return jsonify({"error": "Non autorisé"}), 403

    try:
        conn = get_conn()
        cur  = conn.cursor()

        cur.execute("DELETE FROM follows WHERE produit_id = %s", (produit_id,))
        cur.execute("DELETE FROM stats_produit WHERE produit_id = %s", (produit_id,))
        cur.execute("DELETE FROM produit WHERE id_produit = %s RETURNING id_produit", (produit_id,))

        deleted = cur.fetchone()

        conn.commit()
        cur.close()
        conn.close()

        if not deleted:
            return jsonify({"error": "Produit introuvable"}), 404

        return jsonify({"message": "Produit supprimé"})

    except Exception as e:
        print("ERREUR DELETE:", e)
        return jsonify({"error": str(e)}), 500

# =================================================================
# UPDATE STATS
# - user_id = 0 si pas de session (visiteur anonyme accepté)
# - ON CONFLICT garanti par assurer_contrainte_unique() au démarrage
# =================================================================
@app.route('/api/stats/<int:produit_id>/<action>', methods=['POST'])
def update_stats(produit_id, action):
    if action not in ('vue', 'click', 'like'):
        return jsonify({"error": "Action inconnue"}), 400

    user_id = session.get('users_id', 0)

    try:
        conn = get_conn()
        cur  = conn.cursor()

        if action == 'vue':
            cur.execute("""
                INSERT INTO stats_produit (produit_id, user_id, vues, clicks, likes)
                VALUES (%s, %s, 1, 0, 0)
                ON CONFLICT (produit_id, user_id)
                DO UPDATE SET vues = stats_produit.vues + 1
            """, (produit_id, user_id))

        elif action == 'click':
            cur.execute("""
                INSERT INTO stats_produit (produit_id, user_id, vues, clicks, likes)
                VALUES (%s, %s, 0, 1, 0)
                ON CONFLICT (produit_id, user_id)
                DO UPDATE SET clicks = stats_produit.clicks + 1
            """, (produit_id, user_id))

        elif action == 'like':
            cur.execute("""
                INSERT INTO stats_produit (produit_id, user_id, vues, clicks, likes)
                VALUES (%s, %s, 0, 0, 1)
                ON CONFLICT (produit_id, user_id)
                DO UPDATE SET likes = stats_produit.likes + 1
            """, (produit_id, user_id))

        conn.commit()

        # Retourner les totaux agrégés
        cur.execute("""
            SELECT COALESCE(SUM(vues),   0),
                   COALESCE(SUM(clicks), 0),
                   COALESCE(SUM(likes),  0)
            FROM stats_produit
            WHERE produit_id = %s
        """, (produit_id,))
        row    = cur.fetchone()
        cur.close(); conn.close()

        vues   = int(row[0])
        clicks = int(row[1])
        likes  = int(row[2])
        taux   = round(clicks / vues * 100, 2) if vues > 0 else 0

        print(f"✅ STAT [{action}] produit={produit_id} user={user_id} → vues={vues} clicks={clicks} likes={likes}")

        return jsonify({
            "ok"        : True,
            "produit_id": produit_id,
            "vues"      : vues,
            "clicks"    : clicks,
            "likes"     : likes,
            "taux"      : taux
        })

    except Exception as e:
        print(f"❌ ERREUR STATS [{action}] produit={produit_id}:", e)
        return jsonify({"error": str(e)}), 500

# ================= GET STATS =================
@app.route('/api/stats', methods=['GET'])
def get_stats():
    try:
        produits = lire_produits_avec_stats()
        stats    = calculer_stats_produits(produits)
        return jsonify({"stats": stats, "produits": produits})
    except Exception as e:
        print("ERREUR GET STATS:", e)
        return jsonify({"stats": {}, "produits": []})

# =================================================================
@app.route('/api/follow/<int:produit_id>', methods=['POST', 'DELETE', 'GET'])
def follow_produit(produit_id):
    user_id = session.get('users_id')

    # GET : retourner le nombre de followers (et si l'utilisateur suit ou non)
    if request.method == 'GET':
        try:
            conn = get_conn()
            cur  = conn.cursor()

            # Nombre total de followers pour ce produit
            cur.execute(
                "SELECT COUNT(*) FROM follows WHERE produit_id = %s",
                (produit_id,)
            )
            total = int(cur.fetchone()[0])

            # Est-ce que cet utilisateur suit déjà ?
            is_following = False
            if user_id:
                cur.execute(
                    "SELECT 1 FROM follows WHERE produit_id = %s AND user_id = %s",
                    (produit_id, user_id)
                )
                is_following = cur.fetchone() is not None

            cur.close(); conn.close()
            return jsonify({"total": total, "is_following": is_following})
        except Exception as e:
            print("ERREUR GET FOLLOW:", e)
            return jsonify({"error": str(e)}), 500

    # POST / DELETE : nécessite d'être connecté
    if not user_id:
        return jsonify({"error": "Connexion requise pour suivre un produit"}), 401

    try:
        conn = get_conn()
        cur  = conn.cursor()

        if request.method == 'POST':
            # Suivre — ON CONFLICT DO NOTHING évite les doublons
            cur.execute("""
                INSERT INTO follows (produit_id, user_id)
                VALUES (%s, %s)
                ON CONFLICT (produit_id, user_id) DO NOTHING
            """, (produit_id, user_id))
            msg = "Produit suivi"
        else:
            # Ne plus suivre
            cur.execute(
                "DELETE FROM follows WHERE produit_id = %s AND user_id = %s",
                (produit_id, user_id)
            )
            msg = "Produit non suivi"

        conn.commit()

        # Retourner le nouveau total de followers
        cur.execute(
            "SELECT COUNT(*) FROM follows WHERE produit_id = %s",
            (produit_id,)
        )
        total = int(cur.fetchone()[0])
        cur.close(); conn.close()

        print(f"✅ FOLLOW [{request.method}] produit={produit_id} user={user_id} → total={total}")
        return jsonify({"ok": True, "message": msg, "total": total})

    except Exception as e:
        print(f"❌ ERREUR FOLLOW produit={produit_id}:", e)
        return jsonify({"error": str(e)}), 500

# ================= RUN =================
if __name__ == "__main__":
    create_tables()   # 👈 ITO no tena zava-dehibe
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)