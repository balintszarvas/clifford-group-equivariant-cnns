from flax import linen as nn

from modules.conv.convolution import CliffordSteerableConv
from modules.core.norm import MVLayerNorm, GradeNorm
from modules.core.mvgelu import MVGELU


class CSBasicBlock(nn.Module):
    """
    Basic block for the Clifford-steerable ResNet.

    Attributes:
        algebra (object): An instance of CliffordAlgebra defining the algebraic structure.
        in_channels (int): The number of input channels.
        channels (int): The number of hidden channels.
        product_paths_sum (int): The number of non-zero elements in the Cayley table.
            - given by algebra.geometric_product_paths.sum().item()
        norm (bool): Whether to use normalization in the block.
        num_layers (int): The number of layers in the network.
        hidden_dim (int): The number of features in the hidden layers.
        kernel_size (int): The size of the kernel.
        bias_dims (tuple): Dimensions for the bias terms.
        stride (int): The stride of the convolution.
        expansion (int): The expansion factor for the number of channels.
    """

    algebra: object
    in_channels: int
    channels: int
    product_paths_sum: int
    norm: bool
    num_layers: int
    hidden_dim: int
    kernel_size: int
    bias_dims: tuple
    stride: int = 1
    expansion: int = 1
    padding_mode: str = "SAME"

    @nn.compact
    def __call__(self, x):
        """
        Applies the basic block to a multivector input.
            x -> conv1 -> norm1 -> gelu -> conv2 -> norm2 -> x + conv(x) -> gelu -> out

        Args:
            x: The input multivector of shape (N, in_channels, X_1, ..., X_dim, 2**algebra.dim).

        Returns:
            The output multivector of shape (N, channels, X_1, ..., X_dim, 2**algebra.dim).
        """
        conv_config = {
            "algebra": self.algebra,
            "num_layers": self.num_layers,
            "hidden_dim": self.hidden_dim,
            "kernel_size": self.kernel_size,
            "bias_dims": self.bias_dims,
            "product_paths_sum": self.product_paths_sum,
            "padding_mode": self.padding_mode,
        }

        out = CliffordSteerableConv(
            c_in=self.in_channels,
            c_out=self.channels,
            stride=self.stride,
            bias=True,
            **conv_config
        )(x)
        out = MVLayerNorm(self.algebra)(out) if self.norm else out
        out = MVGELU()(out)

        out = CliffordSteerableConv(
            c_in=self.channels,
            c_out=self.channels,
            stride=self.stride,
            padding=True,
            bias=True,
            **conv_config
        )(out)
        out = MVLayerNorm(self.algebra)(out) if self.norm else out

        # shortcut connection
        if self.stride != 1 or self.in_channels != self.expansion * self.channels:
            x = CliffordSteerableConv(
                c_in=self.in_channels,
                c_out=self.expansion * self.channels,
                stride=self.stride,
                padding=True,
                bias=True,
                **conv_config
            )(x)
            x = MVLayerNorm(self.algebra)(x) if self.norm else x

        out += x
        out = MVGELU()(out)
        return out


class CSResNetMnist(nn.Module):
    """
    Clifford-steerable ResNet-based CLassifier.
    It takes a stack of MNIST.

    Attributes:
        algebra (object): An instance of CliffordAlgebra defining the algebraic structure.
        c_in (int): The number of input channels.
        c_out (int): The number of output channels.
        hidden_channels (int): The number of hidden channels.
        kernel_num_layers (int): The number of layers in the network.
        kernel_hidden_dim (int): The number of features in the hidden layers.
        kernel_size (int): The size of the kernel.
        bias_dims (tuple): Dimensions for the bias terms.
        out_features (int): The number of output features.
        product_paths_sum (int): The number of non-zero elements in the Cayley table.
            - given by algebra.geometric_product_paths.sum().item()
        blocks (tuple): The number of blocks in the network.
        norm (bool): Whether to use normalization in the network.
        make_channels (bool): Whether to use the input and output channels as features.
            - only used for non-Euclidean data.
    """

    algebra: object
    c_in: int
    c_out: int
    hidden_channels: int
    kernel_num_layers: int
    kernel_hidden_dim: int
    kernel_size: int
    bias_dims: tuple
    product_paths_sum: int
    blocks: tuple = (2, 2, 2, 2)
    norm: bool = True
    make_channels: bool = False
    padding_mode: str = "SAME"

    def setup(self):
        self.conv_config = {
            "algebra": self.algebra,
            "kernel_size": 1,
            "bias_dims": self.bias_dims,
            "num_layers": self.kernel_num_layers,
            "hidden_dim": self.kernel_hidden_dim,
            "product_paths_sum": self.product_paths_sum,
            "padding_mode": self.padding_mode,
        }

        self.block_config = {
            "algebra": self.algebra,
            "in_channels": self.hidden_channels,
            "channels": self.hidden_channels,
            "product_paths_sum": self.product_paths_sum,
            "norm": self.norm,
            "num_layers": self.kernel_num_layers,
            "hidden_dim": self.kernel_hidden_dim,
            "kernel_size": self.kernel_size,
            "bias_dims": self.bias_dims,
            "padding_mode": self.padding_mode,
        }

    @nn.compact
    def __call__(self, x):
        """
        Forward pass of the model.
            x -> 2 1x1 convolutions -> N basic blocks -> 2 1x1 convolutions -> norm -> dense -> out

        Args:
            x: The input multivector of shape (N, time_history, X_1, ..., X_dim, 2**algebra.dim).

        Returns:
            The output multivector of shape (N, time_future, X_1, ..., X_dim, 2**algebra.dim).
        """
        # Embedding convolutional layers
        in_channels = self.c_in if not self.make_channels else 1
        out_channels = self.c_out if not self.make_channels else 1

        x = CliffordSteerableConv(
            c_in=in_channels, c_out=self.hidden_channels, **self.conv_config
        )(x)
        x = MVGELU()(x)
        x = CliffordSteerableConv(
            c_in=self.hidden_channels, c_out=self.hidden_channels, **self.conv_config
        )(x)
        x = MVGELU()(x)

        # Basic blocks
        for num_blocks in self.blocks:
            for _ in range(num_blocks):
                x = CSBasicBlock(**self.block_config)(x)

        # Output convolutional layers
        x = CliffordSteerableConv(
            c_in=self.hidden_channels, c_out=self.hidden_channels, **self.conv_config
        )(x)
        x = MVGELU()(x)
        x = CliffordSteerableConv(
            c_in=self.hidden_channels, c_out=out_channels, **self.conv_config
        )(x)

        #Classifying layer
        x = GradeNorm(self.algebra)(x)

        x = x.reshape(x.shape[0], -1)
    
        x = nn.Dense(features=self.out_features)(x)
        return x
