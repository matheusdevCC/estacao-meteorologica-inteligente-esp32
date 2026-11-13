# Como publicar este projeto no GitHub

1. Entre em https://github.com e faça login.
2. Clique em **New repository**.
3. Nome sugerido: `estacao-meteorologica-inteligente-esp32`.
4. Selecione **Public** caso a entrega exija acesso público (ou **Private** se a instituição aceitar).
5. **Não marque** as opções de criar README, .gitignore ou licença: estes arquivos já vêm no pacote, evitando conflito.
6. Clique em **Create repository**.
7. Na página do repositório, escolha **uploading an existing file** ou **Add file > Upload files**.
8. **Descompacte o ZIP do projeto** e arraste todos os arquivos e pastas para a área de envio. Não envie o ZIP fechado se quiser que o README apareça automaticamente.
9. Clique em **Commit changes**.
10. Verifique se as fotos, o diagrama e os dois GIFs aparecem no README. Copie o endereço público para a entrega.

## O que ainda pode ser acrescentado

- GIF da montagem física (assim que o vídeo de montagem for enviado).
- Fotos próximas dos módulos e da alimentação para confirmar o desenho elétrico final.
- Teste/calibração do BMP280 e do MQ-135, se esses ajustes forem concluídos.

## Alternativa via Git

```bash
git init
git add .
git commit -m "Documentacao inicial da estacao meteorologica ESP32"
git branch -M main
git remote add origin https://github.com/SEU-USUARIO/estacao-meteorologica-inteligente-esp32.git
git push -u origin main
```

Substitua `SEU-USUARIO` pelo perfil de GitHub que criar o repositório; não há link real do repositório até essa etapa.
