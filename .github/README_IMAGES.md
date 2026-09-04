# B3 DateTime API — Assets visuais

Recursos visuais do projeto. Só o `logo.svg` é usado pelo repositório; os ícones são a
arte-fonte para gerar favicons e ícones de aplicativo quando necessário.

## 📁 Arquivos

| Arquivo | Uso |
|---------|-----|
| `logo.svg` | Logo horizontal (400×120 px). Usado no cabeçalho do `README.md`. |
| `icon.svg` | Ícone completo (512×512 px). Arte-fonte; não é usado pela aplicação. |
| `icon-simple.svg` | Ícone simplificado (256×256 px) para tamanhos pequenos. Arte-fonte. |

O favicon servido pela API em `/static/favicon.png` está em `src/static/assets/favicon.png`,
junto com os demais assets da documentação (Swagger UI e ReDoc).

## 🎨 Como o README usa o logo

O cabeçalho é HTML centralizado, para controlar a largura:

```html
<div align="center">
  <img src=".github/logo.svg" alt="B3 DateTime API" width="400">
</div>
```

## 🖼️ Gerando favicons a partir dos ícones

**ImageMagick:**

```bash
convert .github/icon-simple.svg -resize 16x16 favicon-16.png
convert .github/icon-simple.svg -resize 32x32 favicon-32.png
convert .github/icon-simple.svg -resize 180x180 apple-touch-icon.png
convert .github/icon-simple.svg -resize 512x512 icon-512.png
```

**Online:** [Favicon Generator](https://favicon.io/favicon-converter/) · [Real Favicon Generator](https://realfavicongenerator.net/)

Tamanhos usuais: 16×16 e 32×32 (favicon), 180×180 (Apple Touch Icon), 192×192 e 512×512 (PWA).

## 🎨 Paleta de cores

- **Azul escuro**: `#1e40af`
- **Azul médio**: `#3b82f6`
- **Azul claro**: `#60a5fa`
- **Fundo**: `#0f172a`
- **Texto secundário**: `#94a3b8`
- **Branco**: `#ffffff`

## 📝 Licença

Os assets seguem a mesma licença do repositório (MIT).
