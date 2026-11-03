# TwinOps çalışma kuralları

- Kullanıcı gerçek veri veya gerçek fabrika bekliyorsa, veri edinilemediğinde bunu ilk anlamlı güncellemede açıkça bildir. Kod/pipeline hazırlanmasını gerçek verinin edinilmesi veya gerçek fabrikanın test edilmesi gibi sunma.
- Sentetik örnekleri gerçek Bosch verisi olarak tanıtma. Hangi veri kaynağının aktif olduğunu kullanıcıya açıkça söyle.
- Yeni Python sürecindeki testler, zaten açık Streamlit sunucusunun çalıştığını kanıtlamaz. Çalışan uygulamayı tarayıcıda ve gerçek bridge çıktılarıyla doğrula; eski modüllerin bellekte kalmasını hesaba kat.
- Blender veri köprüsü güncellemesi ile Blender sahnesi/görünüm değişikliğini ayrı anlat. Yapılmayan veya doğrulanmayan görsel çalışmayı tamamlanmış sayma.
- Değişiklikleri dosya adı, kodda mevcut uzun `# =========================================================` başlığı ve kısa gerekçe ile açıkla. Kullanıcının nelerin değiştiğini anlamasını sağla.
