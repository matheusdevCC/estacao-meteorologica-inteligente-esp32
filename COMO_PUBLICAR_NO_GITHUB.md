# Atualizacao pelo GitHub Desktop

Repositorio ja criado: https://github.com/matheusdevCC/estacao-meteorologica-inteligente-esp32

1. No GitHub Desktop, abra o repositorio `estacao-meteorologica-inteligente-esp32`.
2. Clique em **Repository > Show in Explorer** para abrir a pasta clonada no Windows.
3. Extraia o arquivo ZIP desta entrega em uma pasta temporaria (fora do repositorio).
4. Entre na pasta extraida e copie **o conteudo** (README.md, `codigo/`, `docs/`, `.gitignore`, este guia) para a **raiz** do repositorio clonado, substituindo os arquivos antigos quando solicitado.
5. NAO copie pastas intermediarias nem mexa na pasta oculta `.git`.
6. Volte ao GitHub Desktop e confira as alteracoes em **Changes**.
7. Preencha **Summary** com `Atualizar API, geometria e status MQ-135`.
8. Clique em **Commit to main**, depois em **Push origin** (ou **Publish branch**, se esse for o botao mostrado no aplicativo).
9. Acesse o link acima e confira se o `README.md` aparece na pagina inicial e se imagens e GIFs sao exibidos corretamente.

## Para testar antes da publicacao

- Abra `codigo/main.py` no Thonny (interpretador MicroPython/ESP32).
- O modo padrao `MQ_MODO = 'demonstracao'` exibe **0** no painel, de forma explicitamente identificada como demonstracao. O AO do MQ-135 deve ficar desconectado enquanto nao houver adaptacao eletrica da tensao.
- Execute com F5 e conecte-se a rede Wi-Fi `Estacao-ESP32` (senha `Estacao2026`).
- Abra `http://192.168.4.1/` para o painel e `http://192.168.4.1/docs` para a documentacao da API.
- Abra `http://192.168.4.1/api` para conferir os campos `mq_raw`, `mq_origem` e `mq_status`.

## Limitacoes assumidas na documentacao

- A pressao do BMP280 ainda exige verificacao/calibracao.
- MQ-135 mostra zero demonstrativo na interface; nao ha medida de gases validada.
- O mapa e um plano cartesiano local didatico, nao GPS nem mapa de ruas.
- O servidor roda no proprio ESP32; nao ha banco de dados remoto nesta versao.
